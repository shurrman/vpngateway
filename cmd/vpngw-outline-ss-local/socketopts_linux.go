//go:build linux

package main

import "syscall"

func applySocketOptions(c syscall.RawConn, mark int, outboundInterface string) error {
	var controlErr error
	err := c.Control(func(fd uintptr) {
		if mark > 0 {
			if e := syscall.SetsockoptInt(int(fd), syscall.SOL_SOCKET, syscall.SO_MARK, mark); e != nil {
				controlErr = e
				return
			}
		}
		if outboundInterface != "" {
			if e := syscall.SetsockoptString(int(fd), syscall.SOL_SOCKET, syscall.SO_BINDTODEVICE, outboundInterface); e != nil {
				controlErr = e
			}
		}
	})
	if err != nil {
		return err
	}
	return controlErr
}
