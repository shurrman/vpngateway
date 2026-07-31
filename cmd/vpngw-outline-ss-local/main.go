package main

import (
	"context"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/Jigsaw-Code/outline-sdk/transport"
	"github.com/Jigsaw-Code/outline-sdk/transport/shadowsocks"
)

const (
	socksCmdConnect      = 0x01
	socksCmdUDPAssociate = 0x03
	udpReadPollInterval  = time.Second
)

var udpAssociateIdle = 15 * time.Second

type config struct {
	Listen            string `json:"listen"`
	Server            string `json:"server"`
	Method            string `json:"method"`
	Password          string `json:"password"`
	PrefixB64         string `json:"prefix_b64"`
	OutboundInterface string `json:"outbound_interface"`
	Mark              int    `json:"mark"`
}

func main() {
	configPath := flag.String("config", "", "path to JSON config")
	flag.Parse()
	if *configPath == "" {
		log.Fatal("-config is required")
	}

	cfg, err := readConfig(*configPath)
	if err != nil {
		log.Fatal(err)
	}

	key, err := shadowsocks.NewEncryptionKey(cfg.Method, cfg.Password)
	if err != nil {
		log.Fatal(err)
	}
	prefix, err := base64.StdEncoding.DecodeString(cfg.PrefixB64)
	if err != nil {
		log.Fatal(err)
	}

	dialer := &net.Dialer{
		Timeout:   10 * time.Second,
		KeepAlive: 30 * time.Second,
		Control: func(_, _ string, c syscall.RawConn) error {
			return applySocketOptions(c, cfg.Mark, cfg.OutboundInterface)
		},
	}
	ssDialer, err := shadowsocks.NewStreamDialer(&transport.TCPEndpoint{
		Address: cfg.Server,
		Dialer:  *dialer,
	}, key)
	if err != nil {
		log.Fatal(err)
	}
	ssDialer.SaltGenerator = shadowsocks.NewPrefixSaltGenerator(prefix)
	ssPacketListener, err := shadowsocks.NewPacketListener(&transport.UDPEndpoint{
		Address: cfg.Server,
		Dialer:  *dialer,
	}, key)
	if err != nil {
		log.Fatal(err)
	}
	ssPacketListener.SetSaltGenerator(shadowsocks.NewPrefixSaltGenerator(prefix))

	ln, err := net.Listen("tcp", cfg.Listen)
	if err != nil {
		log.Fatal(err)
	}
	log.Printf("outline ss local listening on %s (tcp+udp)", cfg.Listen)
	for {
		conn, err := ln.Accept()
		if err != nil {
			log.Printf("accept: %v", err)
			continue
		}
		go handleSocks(conn, ssDialer, ssPacketListener)
	}
}

func readConfig(path string) (*config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var cfg config
	if err := json.Unmarshal(data, &cfg); err != nil {
		return nil, err
	}
	if cfg.Listen == "" || cfg.Server == "" || cfg.Method == "" || cfg.Password == "" || cfg.PrefixB64 == "" {
		return nil, errors.New("listen, server, method, password, and prefix_b64 are required")
	}
	return &cfg, nil
}

type streamDialer interface {
	DialStream(context.Context, string) (transport.StreamConn, error)
}

type packetListener interface {
	ListenPacket(context.Context) (net.PacketConn, error)
}

type socksRequest struct {
	cmd    byte
	target string
}

func handleSocks(client net.Conn, dialer streamDialer, packets packetListener) {
	defer client.Close()
	req, err := socksHandshake(client)
	if err != nil {
		if !strings.Contains(err.Error(), "unsupported SOCKS command") {
			log.Printf("socks handshake: %v", err)
		}
		return
	}
	if req.cmd == socksCmdUDPAssociate {
		if err := handleUDPAssociate(client, packets); err != nil {
			log.Printf("udp associate: %v", err)
		}
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	remote, err := dialer.DialStream(ctx, req.target)
	cancel()
	if err != nil {
		log.Printf("dial %s: %v", req.target, err)
		writeSocksReply(client, 0x05)
		return
	}
	defer remote.Close()
	if err := writeSocksReply(client, 0x00); err != nil {
		return
	}
	errCh := make(chan error, 2)
	go func() {
		_, err := io.Copy(remote, client)
		errCh <- err
	}()
	go func() {
		_, err := io.Copy(client, remote)
		errCh <- err
	}()
	<-errCh
}

func socksHandshake(conn net.Conn) (*socksRequest, error) {
	head := make([]byte, 2)
	if _, err := io.ReadFull(conn, head); err != nil {
		return nil, err
	}
	if head[0] != 0x05 {
		return nil, errors.New("only SOCKS5 is supported")
	}
	methods := make([]byte, int(head[1]))
	if _, err := io.ReadFull(conn, methods); err != nil {
		return nil, err
	}
	if _, err := conn.Write([]byte{0x05, 0x00}); err != nil {
		return nil, err
	}

	req := make([]byte, 4)
	if _, err := io.ReadFull(conn, req); err != nil {
		return nil, err
	}
	if req[0] != 0x05 {
		return nil, errors.New("invalid SOCKS request")
	}
	if req[1] != socksCmdConnect && req[1] != socksCmdUDPAssociate {
		_, _ = readSocksAddr(conn, req[3])
		portBuf := make([]byte, 2)
		_, _ = io.ReadFull(conn, portBuf)
		_ = writeSocksReply(conn, 0x07)
		return nil, fmt.Errorf("unsupported SOCKS command: %d", req[1])
	}

	host, err := readSocksAddr(conn, req[3])
	if err != nil {
		return nil, err
	}
	portBuf := make([]byte, 2)
	if _, err := io.ReadFull(conn, portBuf); err != nil {
		return nil, err
	}
	port := binary.BigEndian.Uint16(portBuf)
	return &socksRequest{cmd: req[1], target: net.JoinHostPort(host, strconv.Itoa(int(port)))}, nil
}

func handleUDPAssociate(control net.Conn, packets packetListener) error {
	udpRelay, err := net.ListenUDP("udp", &net.UDPAddr{IP: net.ParseIP("127.0.0.1"), Port: 0})
	if err != nil {
		_ = writeSocksReply(control, 0x01)
		return err
	}
	defer udpRelay.Close()

	ssPackets, err := packets.ListenPacket(context.Background())
	if err != nil {
		_ = writeSocksReply(control, 0x05)
		return err
	}
	defer ssPackets.Close()

	if err := writeSocksReplyAddr(control, 0x00, udpRelay.LocalAddr()); err != nil {
		return err
	}

	done := make(chan struct{})
	activity := make(chan struct{}, 1)
	clientAddrCh := make(chan net.Addr, 1)
	go relaySocksUDPToShadow(udpRelay, ssPackets, clientAddrCh, activity, done)
	go relayShadowUDPToSocks(ssPackets, udpRelay, clientAddrCh, activity, done)

	controlDone := make(chan error, 1)
	go func() {
		_, err := io.Copy(io.Discard, control)
		controlDone <- err
	}()

	timer := time.NewTimer(udpAssociateIdle)
	defer timer.Stop()
	for {
		select {
		case err := <-controlDone:
			close(done)
			return err
		case <-activity:
			if !timer.Stop() {
				select {
				case <-timer.C:
				default:
				}
			}
			timer.Reset(udpAssociateIdle)
		case <-timer.C:
			log.Printf("udp associate idle timeout after %s", udpAssociateIdle)
			_ = control.Close()
			close(done)
			return nil
		}
	}
}

func signalActivity(activity chan<- struct{}) {
	select {
	case activity <- struct{}{}:
	default:
	}
}

func relaySocksUDPToShadow(udpRelay *net.UDPConn, ssPackets net.PacketConn, clientAddrCh chan net.Addr, activity chan<- struct{}, done <-chan struct{}) {
	buf := make([]byte, 64*1024)
	for {
		_ = udpRelay.SetReadDeadline(time.Now().Add(udpReadPollInterval))
		n, clientAddr, err := udpRelay.ReadFrom(buf)
		select {
		case <-done:
			return
		default:
		}
		if err != nil {
			if ne, ok := err.(net.Error); ok && ne.Timeout() {
				continue
			}
			log.Printf("udp relay read: %v", err)
			return
		}
		signalActivity(activity)
		target, payload, err := parseSocksUDPDatagram(buf[:n])
		if err != nil {
			log.Printf("udp relay parse: %v", err)
			continue
		}
		select {
		case clientAddrCh <- clientAddr:
		default:
			select {
			case <-clientAddrCh:
			default:
			}
			clientAddrCh <- clientAddr
		}
		if _, err := ssPackets.WriteTo(payload, target); err != nil {
			log.Printf("ss udp write %s: %v", target.String(), err)
		}
	}
}

func relayShadowUDPToSocks(ssPackets net.PacketConn, udpRelay *net.UDPConn, clientAddrCh <-chan net.Addr, activity chan<- struct{}, done <-chan struct{}) {
	buf := make([]byte, 64*1024)
	var clientAddr net.Addr
	for {
		if clientAddr == nil {
			select {
			case <-done:
				return
			case clientAddr = <-clientAddrCh:
			}
		}
		_ = ssPackets.SetReadDeadline(time.Now().Add(time.Second))
		n, srcAddr, err := ssPackets.ReadFrom(buf)
		select {
		case <-done:
			return
		default:
		}
		if err != nil {
			if ne, ok := err.(net.Error); ok && ne.Timeout() {
				select {
				case clientAddr = <-clientAddrCh:
				default:
				}
				continue
			}
			log.Printf("ss udp read: %v", err)
			return
		}
		signalActivity(activity)
		select {
		case clientAddr = <-clientAddrCh:
		default:
		}
		packet, err := buildSocksUDPDatagram(srcAddr, buf[:n])
		if err != nil {
			log.Printf("udp relay build: %v", err)
			continue
		}
		if _, err := udpRelay.WriteTo(packet, clientAddr); err != nil {
			log.Printf("udp relay write: %v", err)
		}
	}
}

func parseSocksUDPDatagram(packet []byte) (net.Addr, []byte, error) {
	if len(packet) < 4 {
		return nil, nil, errors.New("short SOCKS UDP packet")
	}
	if packet[0] != 0 || packet[1] != 0 {
		return nil, nil, errors.New("invalid SOCKS UDP reserved bytes")
	}
	if packet[2] != 0 {
		return nil, nil, errors.New("SOCKS UDP fragmentation is not supported")
	}
	host, port, off, err := readSocksAddrBytes(packet, 3)
	if err != nil {
		return nil, nil, err
	}
	addr, err := transport.MakeNetAddr("udp", net.JoinHostPort(host, strconv.Itoa(int(port))))
	if err != nil {
		return nil, nil, err
	}
	return addr, packet[off:], nil
}

func buildSocksUDPDatagram(addr net.Addr, payload []byte) ([]byte, error) {
	out := []byte{0x00, 0x00, 0x00}
	var err error
	out, err = appendSocksAddr(out, addr.String())
	if err != nil {
		return nil, err
	}
	return append(out, payload...), nil
}

func readSocksAddrBytes(packet []byte, off int) (string, uint16, int, error) {
	if off >= len(packet) {
		return "", 0, off, errors.New("missing address type")
	}
	atyp := packet[off]
	off++
	var host string
	switch atyp {
	case 0x01:
		if off+4 > len(packet) {
			return "", 0, off, errors.New("short IPv4 address")
		}
		host = net.IP(packet[off : off+4]).String()
		off += 4
	case 0x03:
		if off >= len(packet) {
			return "", 0, off, errors.New("short domain length")
		}
		l := int(packet[off])
		off++
		if off+l > len(packet) {
			return "", 0, off, errors.New("short domain address")
		}
		host = string(packet[off : off+l])
		off += l
	case 0x04:
		if off+16 > len(packet) {
			return "", 0, off, errors.New("short IPv6 address")
		}
		host = net.IP(packet[off : off+16]).String()
		off += 16
	default:
		return "", 0, off, fmt.Errorf("unsupported address type: %d", atyp)
	}
	if off+2 > len(packet) {
		return "", 0, off, errors.New("short port")
	}
	port := binary.BigEndian.Uint16(packet[off : off+2])
	off += 2
	return host, port, off, nil
}

func readSocksAddr(conn net.Conn, atyp byte) (string, error) {
	switch atyp {
	case 0x01:
		buf := make([]byte, 4)
		if _, err := io.ReadFull(conn, buf); err != nil {
			return "", err
		}
		return net.IP(buf).String(), nil
	case 0x03:
		lenBuf := make([]byte, 1)
		if _, err := io.ReadFull(conn, lenBuf); err != nil {
			return "", err
		}
		buf := make([]byte, int(lenBuf[0]))
		if _, err := io.ReadFull(conn, buf); err != nil {
			return "", err
		}
		return string(buf), nil
	case 0x04:
		buf := make([]byte, 16)
		if _, err := io.ReadFull(conn, buf); err != nil {
			return "", err
		}
		return net.IP(buf).String(), nil
	default:
		return "", fmt.Errorf("unsupported address type: %d", atyp)
	}
}

func writeSocksReply(conn net.Conn, rep byte) error {
	_, err := conn.Write([]byte{0x05, rep, 0x00, 0x01, 0, 0, 0, 0, 0, 0})
	return err
}

func writeSocksReplyAddr(conn net.Conn, rep byte, addr net.Addr) error {
	out := []byte{0x05, rep, 0x00}
	var err error
	out, err = appendSocksAddr(out, addr.String())
	if err != nil {
		return err
	}
	_, err = conn.Write(out)
	return err
}

func appendSocksAddr(out []byte, addr string) ([]byte, error) {
	host, portStr, err := net.SplitHostPort(addr)
	if err != nil {
		return nil, err
	}
	port, err := strconv.Atoi(portStr)
	if err != nil || port < 0 || port > 65535 {
		return nil, fmt.Errorf("invalid port: %s", portStr)
	}
	ip := net.ParseIP(host)
	if ip4 := ip.To4(); ip4 != nil {
		out = append(out, 0x01)
		out = append(out, ip4...)
	} else if ip16 := ip.To16(); ip16 != nil {
		out = append(out, 0x04)
		out = append(out, ip16...)
	} else {
		if len(host) > 255 {
			return nil, errors.New("domain too long")
		}
		out = append(out, 0x03, byte(len(host)))
		out = append(out, []byte(host)...)
	}
	var portBuf [2]byte
	binary.BigEndian.PutUint16(portBuf[:], uint16(port))
	out = append(out, portBuf[:]...)
	return out, nil
}
