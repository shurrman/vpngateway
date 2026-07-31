package main

import (
	"context"
	"errors"
	"io"
	"net"
	"testing"
	"time"
)

type testPacketListener struct{}

func (testPacketListener) ListenPacket(context.Context) (net.PacketConn, error) {
	return net.ListenPacket("udp", "127.0.0.1:0")
}

func TestUDPAssociateIdleTimeoutClosesControl(t *testing.T) {
	oldIdle := udpAssociateIdle
	udpAssociateIdle = 50 * time.Millisecond
	t.Cleanup(func() { udpAssociateIdle = oldIdle })

	server, client := net.Pipe()
	defer client.Close()

	done := make(chan error, 1)
	go func() {
		done <- handleUDPAssociate(server, testPacketListener{})
	}()

	if err := client.SetReadDeadline(time.Now().Add(time.Second)); err != nil {
		t.Fatal(err)
	}
	reply := make([]byte, 10)
	if _, err := io.ReadFull(client, reply); err != nil {
		t.Fatalf("read SOCKS reply: %v", err)
	}
	if reply[0] != 0x05 || reply[1] != 0x00 {
		t.Fatalf("unexpected SOCKS reply: %v", reply[:2])
	}

	buf := make([]byte, 1)
	_, err := client.Read(buf)
	if err == nil {
		t.Fatal("expected control connection to close after idle timeout")
	}
	if !errors.Is(err, io.EOF) && !errors.Is(err, net.ErrClosed) {
		t.Fatalf("unexpected read error after idle timeout: %v", err)
	}

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("handleUDPAssociate returned error: %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("handleUDPAssociate did not return after idle timeout")
	}
}
