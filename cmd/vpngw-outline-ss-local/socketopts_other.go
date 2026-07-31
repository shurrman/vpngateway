//go:build !linux

package main

import "syscall"

func applySocketOptions(c syscall.RawConn, mark int, outboundInterface string) error {
	return nil
}
