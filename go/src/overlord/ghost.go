// Copyright 2015 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

package overlord

import (
	"bufio"
	"bytes"
	"crypto/sha1"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/pkg/term/termios"
	"github.com/kr/pty"
	"github.com/satori/go.uuid"
	"io"
	"io/ioutil"
	"log"
	"net"
	"net/http"
	"net/rpc"
	"net/rpc/jsonrpc"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

const (
	GHOST_RPC_PORT  = 4499
	DEFAULT_SHELL   = "/bin/bash"
	LOCALHOST       = "localhost"
	PING_INTERVAL   = 10
	PING_TIMEOUT    = 10
	RETRY_INTERVAL  = 2
	READ_TIMEOUT    = 3
	RANDOM_MID      = "##random_mid##"
	BLOCK_SIZE      = 4096
	CONNECT_TIMEOUT = 3
)

// An structure that we be place into download queue.
// In our case since we always execute 'ghost --download' in our pseudo
// terminal so ttyName will always have the form /dev/pts/X
type DownloadInfo struct {
	Ttyname  string
	Filename string
}

type FileOperation struct {
	Action   string
	Filename string
	Perm     int
}

type FileUploadContext struct {
	Ready bool
	Data  chan []byte
}

type TLSSettings struct {
	tlsCertFile string      // TLS certificate in PEM format
	Config      *tls.Config // TLS configuration
}

func NewTLSSettings(tlsCertFile string, enableTLSWithoutVerify bool) *TLSSettings {
	var tlsConfig *tls.Config

	if enableTLSWithoutVerify {
		tlsConfig = &tls.Config{InsecureSkipVerify: true}
	} else if tlsCertFile != "" {
		// Load certificate
		cert, err := ioutil.ReadFile(tlsCertFile)
		if err != nil {
			log.Fatalln(err)
		}
		caCertPool := x509.NewCertPool()
		caCertPool.AppendCertsFromPEM(cert)
		tlsConfig = &tls.Config{
			RootCAs: caCertPool,
			MinVersion: tls.VersionTLS12,
		}
	}

	return &TLSSettings{tlsCertFile, tlsConfig}
}

func (self *TLSSettings) Enabled() bool {
	return self.Config != nil
}

type Ghost struct {
	*RPCCore
	addrs           []string               // List of possible Overlord addresses
	server          *rpc.Server            // RPC server handle
	connectedAddr   string                 // Current connected Overlord address
	tlsSettings     *TLSSettings           // TLS settings
	mode            int                    // mode, see constants.go
	mid             string                 // Machine ID
	sid             string                 // Session ID
	terminalSid     string                 // Associated terminal session ID
	ttyName2Sid     map[string]string      // Mapping between ttyName and Sid
	terminalSid2Pid map[string]int         // Mapping between terminalSid and pid
	propFile        string                 // Properties file filename
	properties      map[string]interface{} // Client properties
	RegisterStatus  string                 // Register status from server response
	reset           bool                   // Whether to reset the connection
	quit            bool                   // Whether to quit the connection
	readChan        chan []byte            // The incoming data channel
	readErrChan     chan error             // The incoming data error channel
	pauseLanDisc    bool                   // Stop LAN discovery
	ttyDevice       string                 // Terminal device to open
	shellCommand    string                 // Shell command to execute
	fileOperation   FileOperation          // File operation name
	downloadQueue   chan DownloadInfo      // Download queue
	upload          FileUploadContext      // File upload context
	port            int                    // Port number to forward
}

func NewGhost(addrs []string, tlsSettings *TLSSettings, mode int, mid string) *Ghost {

	var (
		finalMid string
		err      error
	)

	if mid == RANDOM_MID {
		finalMid = uuid.NewV4().String()
	} else if mid != "" {
		finalMid = mid
	} else {
		finalMid, err = GetMachineID()
		if err != nil {
			log.Fatalln("Unable to get machine ID:", err)
		}
	}
	return &Ghost{
		RPCCore:         NewRPCCore(nil),
		addrs:           addrs,
		tlsSettings:     tlsSettings,
		mode:            mode,
		mid:             finalMid,
		sid:             uuid.NewV4().String(),
		ttyName2Sid:     make(map[string]string),
		terminalSid2Pid: make(map[string]int),
		properties:      make(map[string]interface{}),
		RegisterStatus:  DISCONNECTED,
		reset:           false,
		quit:            false,
		pauseLanDisc:    false,
		downloadQueue:   make(chan DownloadInfo),
		upload:          FileUploadContext{Data: make(chan []byte)},
	}
}

func (self *Ghost) SetSid(sid string) *Ghost {
	self.sid = sid
	return self
}

func (self *Ghost) SetTerminalSid(sid string) *Ghost {
	self.terminalSid = sid
	return self
}

func (self *Ghost) SetPropFile(propFile string) *Ghost {
	self.propFile = propFile
	return self
}

func (self *Ghost) SetTtyDevice(ttyDevice string) *Ghost {
	self.ttyDevice = ttyDevice
	return self
}

func (self *Ghost) SetCommand(command string) *Ghost {
	self.shellCommand = command
	return self
}

func (self *Ghost) SetFileOp(operation, filename string, perm int) *Ghost {
	self.fileOperation.Action = operation
	self.fileOperation.Filename = filename
	self.fileOperation.Perm = perm
	return self
}

func (self *Ghost) SetPort(port int) *Ghost {
	self.port = port
	return self
}

func (self *Ghost) ExistsInAddr(target string) bool {
	for _, x := range self.addrs {
		if target == x {
			return true
		}
	}
	return false
}

func (self *Ghost) LoadProperties() {
	if self.propFile == "" {
		return
	}

	bytes, err := ioutil.ReadFile(self.propFile)
	if err != nil {
		log.Printf("LoadProperties: %s\n", err)
		return
	}

	if err := json.Unmarshal(bytes, &self.properties); err != nil {
		log.Printf("LoadProperties: %s\n", err)
		return
	}
}

func (self *Ghost) OverlordHTTPSEnabled() bool {
	parts := strings.Split(self.connectedAddr, ":")
	conn, err := net.DialTimeout("tcp",
		fmt.Sprintf("%s:%d", parts[0], OVERLORD_HTTP_PORT),
		CONNECT_TIMEOUT*time.Second)
	if err != nil {
		return false
	}
	defer conn.Close()

	conn.Write([]byte("GET\r\n"))
	buf := make([]byte, 16)
	_, err = conn.Read(buf)
	if err != nil {
		return false
	}
	return strings.Index(string(buf), "HTTP") == -1
}

func (self *Ghost) Upgrade() error {
	log.Println("Upgrade: initiating upgrade sequence...")

	exePath, err := GetExecutablePath()
	if err != nil {
		return errors.New("Upgrade: can not find executable path")
	}

	var buffer bytes.Buffer
	var client http.Client

	serverTLSEnabled := self.OverlordHTTPSEnabled()

	if self.tlsSettings.Enabled() && !serverTLSEnabled {
		return errors.New("Upgrade: TLS enforced but found Overlord HTTP server " +
			"without TLS enabled! Possible mis-configuration or DNS/IP spoofing " +
			"detected, abort")
	}

	proto := "http"
	if serverTLSEnabled {
		proto = "https"
	}
	parts := strings.Split(self.connectedAddr, ":")
	url := fmt.Sprintf("%s://%s:%d/upgrade/ghost.%s", proto, parts[0],
		OVERLORD_HTTP_PORT, GetArchString())

	if serverTLSEnabled {
		tr := &http.Transport{TLSClientConfig: self.tlsSettings.Config}
		client = http.Client{Transport: tr, Timeout: CONNECT_TIMEOUT * time.Second}
	} else {
		client = http.Client{Timeout: CONNECT_TIMEOUT * time.Second}
	}

	// Download the sha1sum for ghost for verification
	resp, err := client.Get(url + ".sha1")
	if err != nil || resp.StatusCode != 200 {
		return errors.New("Upgrade: failed to download sha1sum file, abort")
	}
	sha1sumBytes := make([]byte, 40)
	resp.Body.Read(sha1sumBytes)
	sha1sum := strings.Trim(string(sha1sumBytes), "\n ")
	defer resp.Body.Close()

	// Compare the current version of ghost, if sha1 is the same, skip upgrading
	currentSha1sum, _ := GetFileSha1(exePath)

	if currentSha1sum == sha1sum {
		log.Println("Upgrade: ghost is already up-to-date, skipping upgrade")
		return nil
	}

	// Download upgrade version of ghost
	resp2, err := client.Get(url)
	if err != nil || resp2.StatusCode != 200 {
		return errors.New("Upgrade: failed to download upgrade, abort")
	}
	defer resp2.Body.Close()

	_, err = buffer.ReadFrom(resp2.Body)
	if err != nil {
		return errors.New("Upgrade: failed to write upgrade onto disk, abort")
	}

	// Compare SHA1 sum
	if sha1sum != fmt.Sprintf("%x", sha1.Sum(buffer.Bytes())) {
		return errors.New("Upgrade: sha1sum mismatch, abort")
	}

	os.Remove(exePath)
	exeFile, err := os.Create(exePath)
	if err != nil {
		return errors.New("Upgrade: can not open ghost executable for writing")
	}
	_, err = buffer.WriteTo(exeFile)
	if err != nil {
		return errors.New(fmt.Sprintf("Upgrade: %s", err))
	}
	exeFile.Close()

	err = os.Chmod(exePath, 0755)
	if err != nil {
		return errors.New(fmt.Sprintf("Upgrade: %s", err))
	}

	log.Println("Upgrade: restarting ghost...")
	os.Args[0] = exePath
	return syscall.Exec(exePath, os.Args, os.Environ())
}

func (self *Ghost) handleTerminalRequest(req *Request) error {
	type RequestParams struct {
		Sid       string `json:"sid"`
		TtyDevice string `json:"tty_device"`
	}

	var params RequestParams
	if err := json.Unmarshal(req.Params, &params); err != nil {
		return err
	}

	go func() {
		log.Printf("Received terminal command, Terminal agent %s spawned\n", params.Sid)
		addrs := []string{self.connectedAddr}
		// Terminal sessions are identified with session ID, thus we don't care
		// machine ID and can make them random.
		g := NewGhost(addrs, self.tlsSettings, TERMINAL, RANDOM_MID).SetSid(
			params.Sid).SetTtyDevice(params.TtyDevice)
		g.Start(false, false)
	}()

	res := NewResponse(req.Rid, SUCCESS, nil)
	return self.SendResponse(res)
}

func (self *Ghost) handleShellRequest(req *Request) error {
	type RequestParams struct {
		Sid string `json:"sid"`
		Cmd string `json:"command"`
	}

	var params RequestParams
	if err := json.Unmarshal(req.Params, &params); err != nil {
		return err
	}

	go func() {
		log.Printf("Received shell command: %s, Shell agent %s spawned\n", params.Cmd, params.Sid)
		addrs := []string{self.connectedAddr}
		// Shell sessions are identified with session ID, thus we don't care
		// machine ID and can make them random.
		g := NewGhost(addrs, self.tlsSettings, SHELL, RANDOM_MID).SetSid(
			params.Sid).SetCommand(params.Cmd)
		g.Start(false, false)
	}()

	res := NewResponse(req.Rid, SUCCESS, nil)
	return self.SendResponse(res)
}

func (self *Ghost) handleFileDownloadRequest(req *Request) error {
	type RequestParams struct {
		Sid      string `json:"sid"`
		Filename string `json:"filename"`
	}

	var params RequestParams
	if err := json.Unmarshal(req.Params, &params); err != nil {
		return err
	}

	filename := params.Filename
	if !strings.HasPrefix(filename, "/") {
		home := os.Getenv("HOME")
		if home == "" {
			home = "/tmp"
		}
		filename = filepath.Join(home, filename)
	}

	f, err := os.Open(filename)
	if err != nil {
		res := NewResponse(req.Rid, err.Error(), nil)
		return self.SendResponse(res)
	}
	f.Close()

	go func() {
		log.Printf("Received file_download command, File agent %s spawned\n", params.Sid)
		addrs := []string{self.connectedAddr}
		g := NewGhost(addrs, self.tlsSettings, FILE, RANDOM_MID).SetSid(
			params.Sid).SetFileOp("download", filename, 0)
		g.Start(false, false)
	}()

	res := NewResponse(req.Rid, SUCCESS, nil)
	return self.SendResponse(res)
}

func (self *Ghost) handleFileUploadRequest(req *Request) error {
	type RequestParams struct {
		Sid         string `json:"sid"`
		TerminalSid string `json:"terminal_sid"`
		Filename    string `json:"filename"`
		Dest        string `json:"dest"`
		Perm        int    `json:"perm"`
		CheckOnly   bool   `json:"check_only"`
	}

	var params RequestParams
	if err := json.Unmarshal(req.Params, &params); err != nil {
		return err
	}

	targetDir := os.Getenv("HOME")
	if targetDir == "" {
		targetDir = "/tmp"
	}

	destPath := params.Dest
	if destPath != "" {
		if !filepath.IsAbs(destPath) {
			destPath = filepath.Join(targetDir, destPath)
		}

		st, err := os.Stat(destPath)
		if err == nil && st.Mode().IsDir() {
			destPath = filepath.Join(destPath, params.Filename)
		}
	} else {
		if params.TerminalSid != "" {
			if pid, ok := self.terminalSid2Pid[params.TerminalSid]; ok {
				cwd, err := os.Readlink(fmt.Sprintf("/proc/%d/cwd", pid))
				if err == nil {
					targetDir = cwd
				}
			}
		}
		destPath = filepath.Join(targetDir, params.Filename)
	}

	os.MkdirAll(filepath.Dir(destPath), 0755)

	if f, err := os.Create(destPath); err != nil {
		res := NewResponse(req.Rid, err.Error(), nil)
		return self.SendResponse(res)
	} else {
		f.Close()
	}

	// If not check_only, spawn FILE mode ghost agent to handle upload
	if !params.CheckOnly {
		go func() {
			log.Printf("Received file_upload command, File agent %s spawned\n",
				params.Sid)
			addrs := []string{self.connectedAddr}
			g := NewGhost(addrs, self.tlsSettings, FILE, RANDOM_MID).SetSid(
				params.Sid).SetFileOp("upload", destPath, params.Perm)
			g.Start(false, false)
		}()
	}

	res := NewResponse(req.Rid, SUCCESS, nil)
	return self.SendResponse(res)
}

func (self *Ghost) handleForwardRequest(req *Request) error {
	type RequestParams struct {
		Sid  string `json:"sid"`
		Port int    `json:"port"`
	}

	var params RequestParams
	if err := json.Unmarshal(req.Params, &params); err != nil {
		return err
	}

	go func() {
		log.Printf("Received forward command, Forward agent %s spawned\n", params.Sid)
		addrs := []string{self.connectedAddr}
		g := NewGhost(addrs, self.tlsSettings, FORWARD, RANDOM_MID).SetSid(
			params.Sid).SetPort(params.Port)
		g.Start(false, false)
	}()

	res := NewResponse(req.Rid, SUCCESS, nil)
	return self.SendResponse(res)
}

func (self *Ghost) StartDownloadServer() error {
	log.Println("StartDownloadServer: started")

	defer func() {
		self.quit = true
		self.Conn.Close()
		log.Println("StartDownloadServer: terminated")
	}()

	file, err := os.Open(self.fileOperation.Filename)
	if err != nil {
		return err
	}
	defer file.Close()

	io.Copy(self.Conn, file)
	return nil
}

func (self *Ghost) StartUploadServer() error {
	log.Println("StartUploadServer: started")

	defer func() {
		log.Println("StartUploadServer: terminated")
	}()

	filePath := self.fileOperation.Filename
	dirPath := filepath.Dir(filePath)
	if _, err := os.Stat(dirPath); os.IsNotExist(err) {
		os.MkdirAll(dirPath, 0755)
	}

	file, err := os.Create(filePath)
	if err != nil {
		return err
	}
	defer file.Close()

	for {
		buffer := <-self.upload.Data
		if buffer == nil {
			break
		}
		file.Write(buffer)
	}

	if self.fileOperation.Perm > 0 {
		file.Chmod(os.FileMode(self.fileOperation.Perm))
	}

	return nil
}

func (self *Ghost) handleRequest(req *Request) error {
	var err error
	switch req.Name {
	case "upgrade":
		err = self.Upgrade()
	case "terminal":
		err = self.handleTerminalRequest(req)
	case "shell":
		err = self.handleShellRequest(req)
	case "file_download":
		err = self.handleFileDownloadRequest(req)
	case "clear_to_download":
		err = self.StartDownloadServer()
	case "file_upload":
		err = self.handleFileUploadRequest(req)
	case "forward":
		err = self.handleForwardRequest(req)
	default:
		err = errors.New(`Received unregistered command "` + req.Name + `", ignoring`)
	}
	return err
}

func (self *Ghost) ProcessRequests(reqs []*Request) error {
	for _, req := range reqs {
		if err := self.handleRequest(req); err != nil {
			return err
		}
	}
	return nil
}

func (self *Ghost) Ping() error {
	pingHandler := func(res *Response) error {
		if res == nil {
			self.reset = true
			return errors.New("Ping timeout")
		}
		return nil
	}
	req := NewRequest("ping", nil)
	req.SetTimeout(PING_TIMEOUT)
	return self.SendRequest(req, pingHandler)
}

func (self *Ghost) HandleTTYControl(tty *os.File, control_string string) error {
	// Terminal Command for ghost
	// Implements the Message interface.
	type TerminalCommand struct {
		Command string          `json:"command"`
		Params  json.RawMessage `json:"params"`
	}

	// winsize stores the Height and Width of a terminal.
	type winsize struct {
		height uint16
		width  uint16
	}

	var control TerminalCommand
	err := json.Unmarshal([]byte(control_string), &control)
	if err != nil {
		log.Println("mal-formed JSON request, ignored")
		return nil
	}

	command := control.Command
	if command == "resize" {
		var params []int
		err := json.Unmarshal([]byte(control.Params), &params)
		if err != nil || len(params) != 2 {
			log.Println("mal-formed JSON request, ignored")
			return nil
		}
		ws := &winsize{width: uint16(params[1]), height: uint16(params[0])}
		syscall.Syscall(syscall.SYS_IOCTL, tty.Fd(),
			uintptr(syscall.TIOCSWINSZ), uintptr(unsafe.Pointer(ws)))
	} else {
		return errors.New("Invalid request command " + command)
	}
	return nil
}

func (self *Ghost) getTTYName() (string, error) {
	ttyName, err := os.Readlink(fmt.Sprintf("/proc/%d/fd/0", os.Getpid()))
	if err != nil {
		return "", err
	}
	return ttyName, nil
}

// Spawn a TTY server and forward I/O to the TCP socket.
func (self *Ghost) SpawnTTYServer(res *Response) error {
	log.Println("SpawnTTYServer: started")

	var tty *os.File
	var err error
	stopConn := make(chan bool, 1)

	defer func() {
		self.quit = true
		if tty != nil {
			tty.Close()
		}
		self.Conn.Close()
		log.Println("SpawnTTYServer: terminated")
	}()

	if self.ttyDevice == "" {
		// No TTY device specified, open a PTY (pseudo terminal) instead.
		shell := os.Getenv("SHELL")
		if shell == "" {
			shell = DEFAULT_SHELL
		}

		home := os.Getenv("HOME")
		if home == "" {
			home = "/root"
		}

		// Add ghost executable to PATH
		exePath, err := GetExecutablePath()
		if err == nil {
			os.Setenv("PATH", fmt.Sprintf("%s:%s", filepath.Dir(exePath),
				os.Getenv("PATH")))
		}

		os.Chdir(home)
		cmd := exec.Command(shell)
		tty, err = pty.Start(cmd)
		if err != nil {
			return errors.New(`SpawnTTYServer: Cannot start "` + shell + `", abort`)
		}

		defer func() {
			cmd.Process.Kill()
		}()

		// Register the mapping of sid and ttyName
		ttyName, err := termios.Ptsname(tty.Fd())
		if err != nil {
			return err
		}

		client, err := GhostRPCServer()

		// Ghost could be launched without RPC server, ignore registraion
		if err == nil {
			err = client.Call("rpc.RegisterTTY", []string{self.sid, ttyName},
				&EmptyReply{})
			if err != nil {
				return err
			}

			err = client.Call("rpc.RegisterSession", []string{
				self.sid, strconv.Itoa(cmd.Process.Pid)}, &EmptyReply{})
			if err != nil {
				return err
			}
		}

		go func() {
			io.Copy(self.Conn, tty)
			cmd.Wait()
			stopConn <- true
		}()
	} else {
		// Open a TTY device
		tty, err = os.OpenFile(self.ttyDevice, os.O_RDWR, 0)
		if err != nil {
			return err
		}

		var term syscall.Termios
		err := termios.Tcgetattr(tty.Fd(), &term)
		if err != nil {
			return nil
		}

		termios.Cfmakeraw(&term)
		term.Iflag &= (syscall.IXON | syscall.IXOFF)
		term.Cflag |= syscall.CLOCAL
		term.Ispeed = syscall.B115200
		term.Ospeed = syscall.B115200

		if err = termios.Tcsetattr(tty.Fd(), termios.TCSANOW, &term); err != nil {
			return err
		}

		go func() {
			io.Copy(self.Conn, tty)
			stopConn <- true
		}()
	}

	var control_buffer bytes.Buffer
	var write_buffer bytes.Buffer
	control_state := CONTROL_NONE

	processBuffer := func(buffer []byte) error {
		write_buffer.Reset()
		for len(buffer) > 0 {
			if control_state != CONTROL_NONE {
				index := bytes.IndexByte(buffer, CONTROL_END)
				if index != -1 {
					control_buffer.Write(buffer[:index])
					err := self.HandleTTYControl(tty, control_buffer.String())
					control_state = CONTROL_NONE
					control_buffer.Reset()
					if err != nil {
						return err
					}
					buffer = buffer[index+1:]
				} else {
					control_buffer.Write(buffer)
					buffer = buffer[0:0]
				}
			} else {
				index := bytes.IndexByte(buffer, CONTROL_START)
				if index != -1 {
					control_state = CONTROL_START
					write_buffer.Write(buffer[:index])
					buffer = buffer[index+1:]
				} else {
					write_buffer.Write(buffer)
					buffer = buffer[0:0]
				}
			}
		}
		if write_buffer.Len() != 0 {
			tty.Write(write_buffer.Bytes())
		}
		return nil
	}

	if self.ReadBuffer != "" {
		processBuffer([]byte(self.ReadBuffer))
		self.ReadBuffer = ""
	}

	for {
		select {
		case buffer := <-self.readChan:
			err := processBuffer(buffer)
			if err != nil {
				log.Println("SpawnTTYServer:", err)
			}
		case err := <-self.readErrChan:
			if err == io.EOF {
				log.Println("SpawnTTYServer: connection terminated")
				return nil
			} else {
				return err
			}
		case s := <-stopConn:
			if s {
				return nil
			}
		}
	}

	return nil
}

// Spawn a Shell server and forward input/output from/to the TCP socket.
func (self *Ghost) SpawnShellServer(res *Response) error {
	log.Println("SpawnShellServer: started")

	var err error

	defer func() {
		self.quit = true
		if err != nil {
			self.Conn.Write([]byte(err.Error() + "\n"))
		}
		self.Conn.Close()
		log.Println("SpawnShellServer: terminated")
	}()

	// Execute shell command from HOME directory
	home := os.Getenv("HOME")
	if home == "" {
		home = "/tmp"
	}
	os.Chdir(home)

	// Add ghost executable to PATH
	exePath, err := GetExecutablePath()
	if err == nil {
		os.Setenv("PATH", fmt.Sprintf("%s:%s", os.Getenv("PATH"),
			filepath.Dir(exePath)))
	}

	cmd := exec.Command(DEFAULT_SHELL, "-c", self.shellCommand)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return err
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return err
	}
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return err
	}

	stopConn := make(chan bool, 1)

	if self.ReadBuffer != "" {
		stdin.Write([]byte(self.ReadBuffer))
		self.ReadBuffer = ""
	}

	go io.Copy(self.Conn, stdout)
	go func() {
		io.Copy(self.Conn, stderr)
		stopConn <- true
	}()

	if err = cmd.Start(); err != nil {
		return err
	}

	defer func() {
		time.Sleep(100 * time.Millisecond) // Wait for process to terminate

		process := (*PollableProcess)(cmd.Process)
		_, err = process.Poll()
		// Check if the process is terminated. If not, send SIGTERM to the process,
		// then wait for 1 second.  Send another SIGKILL to make sure the process is
		// terminated.
		if err != nil {
			cmd.Process.Signal(syscall.SIGTERM)
			time.Sleep(time.Second)
			cmd.Process.Kill()
			cmd.Wait()
		}
	}()

	for {
		select {
		case buf := <-self.readChan:
			if len(buf) >= len(STDIN_CLOSED)*2 {
				idx := bytes.Index(buf, []byte(STDIN_CLOSED+STDIN_CLOSED))
				if idx != -1 {
					stdin.Write(buf[:idx])
					stdin.Close()
					continue
				}
			}
			stdin.Write(buf)
		case err := <-self.readErrChan:
			if err == io.EOF {
				log.Println("SpawnShellServer: connection terminated")
				return nil
			} else {
				log.Printf("SpawnShellServer: %s\n", err)
				return err
			}
		case s := <-stopConn:
			if s {
				return nil
			}
		}
	}

	return nil
}

// Initiate file operation.
// The operation could either be 'download' or 'upload'
// This function starts handshake with overlord then execute download sequence.
func (self *Ghost) InitiateFileOperation(res *Response) error {
	if self.fileOperation.Action == "download" {
		fi, err := os.Stat(self.fileOperation.Filename)
		if err != nil {
			return err
		}

		req := NewRequest("request_to_download", map[string]interface{}{
			"terminal_sid": self.terminalSid,
			"filename":     filepath.Base(self.fileOperation.Filename),
			"size":         fi.Size(),
		})

		return self.SendRequest(req, nil)
	} else if self.fileOperation.Action == "upload" {
		self.upload.Ready = true
		req := NewRequest("clear_to_upload", nil)
		req.SetTimeout(-1)
		err := self.SendRequest(req, nil)
		if err != nil {
			return err
		}
		go self.StartUploadServer()
		return nil
	} else {
		return errors.New("InitiateFileOperation: unknown file operation, ignored")
	}
	return nil
}

// Spawn a port forwarding server and forward I/O to the TCP socket.
func (self *Ghost) SpawnPortForwardServer(res *Response) error {
	log.Println("SpawnPortForwardServer: started")

	var err error

	defer func() {
		self.quit = true
		if err != nil {
			self.Conn.Write([]byte(err.Error() + "\n"))
		}
		self.Conn.Close()
		log.Println("SpawnPortForwardServer: terminated")
	}()

	conn, err := net.DialTimeout("tcp", fmt.Sprintf("localhost:%d", self.port),
		CONNECT_TIMEOUT*time.Second)
	if err != nil {
		return err
	}
	defer conn.Close()

	stopConn := make(chan bool, 1)

	if self.ReadBuffer != "" {
		conn.Write([]byte(self.ReadBuffer))
		self.ReadBuffer = ""
	}

	go func() {
		io.Copy(self.Conn, conn)
		stopConn <- true
	}()

	for {
		select {
		case buf := <-self.readChan:
			conn.Write(buf)
		case err := <-self.readErrChan:
			if err == io.EOF {
				log.Println("SpawnPortForwardServer: connection terminated")
				return nil
			} else {
				return err
			}
		case s := <-stopConn:
			if s {
				return nil
			}
		}
	}

	return nil
}

// Register existent to Overlord.
func (self *Ghost) Register() error {
	for _, addr := range self.addrs {
		var (
			conn net.Conn
			err  error
		)

		log.Printf("Trying %s ...\n", addr)
		self.Reset()

		conn, err = net.DialTimeout("tcp", addr, CONNECT_TIMEOUT*time.Second)
		if err == nil {
			log.Println("Connection established, registering...")
			if self.tlsSettings.Enabled() {
				colonPos := strings.LastIndex(addr, ":")
				config := self.tlsSettings.Config
				config.ServerName = addr[:colonPos]
				conn = tls.Client(conn, config)
			}

			self.Conn = conn
			req := NewRequest("register", map[string]interface{}{
				"mid":        self.mid,
				"sid":        self.sid,
				"mode":       self.mode,
				"properties": self.properties,
			})

			registered := func(res *Response) error {
				if res == nil {
					self.reset = true
					return errors.New("Register request timeout")
				} else if res.Response != SUCCESS {
					log.Println("Register:", res.Response)
				} else {
					log.Printf("Registered with Overlord at %s", addr)
					self.connectedAddr = addr
					if err := self.Upgrade(); err != nil {
						log.Println(err)
					}
					self.pauseLanDisc = true
				}
				self.RegisterStatus = res.Response
				return nil
			}

			var handler ResponseHandler
			switch self.mode {
			case AGENT:
				handler = registered
			case TERMINAL:
				handler = self.SpawnTTYServer
			case SHELL:
				handler = self.SpawnShellServer
			case FILE:
				handler = self.InitiateFileOperation
			case FORWARD:
				handler = self.SpawnPortForwardServer
			}
			err = self.SendRequest(req, handler)
			return nil
		}
	}

	return errors.New("Cannot connect to any server")
}

// Initiate a client-side download request
func (self *Ghost) InitiateDownload(info DownloadInfo) {
	go func() {
		addrs := []string{self.connectedAddr}
		g := NewGhost(addrs, self.tlsSettings, FILE, RANDOM_MID).SetTerminalSid(
			self.ttyName2Sid[info.Ttyname]).SetFileOp("download", info.Filename, 0)
		g.Start(false, false)
	}()
}

// Reset all states for a new connection.
func (self *Ghost) Reset() {
	self.ClearRequests()
	self.reset = false
	self.LoadProperties()
	self.RegisterStatus = DISCONNECTED
}

// Main routine for listen to socket messages.
func (self *Ghost) Listen() error {
	readChan, readErrChan := self.SpawnReaderRoutine()
	pingTicker := time.NewTicker(time.Duration(PING_INTERVAL * time.Second))
	reqTicker := time.NewTicker(time.Duration(TIMEOUT_CHECK_SECS * time.Second))

	self.readChan = readChan
	self.readErrChan = readErrChan

	defer func() {
		self.Conn.Close()
		self.pauseLanDisc = false
	}()

	for {
		select {
		case buffer := <-readChan:
			if self.upload.Ready {
				if self.ReadBuffer != "" {
					// Write the leftover from previous ReadBuffer
					self.upload.Data <- []byte(self.ReadBuffer)
					self.ReadBuffer = ""
				}
				self.upload.Data <- buffer
				continue
			}
			reqs := self.ParseRequests(string(buffer), self.RegisterStatus != SUCCESS)
			if self.quit {
				return nil
			}
			if err := self.ProcessRequests(reqs); err != nil {
				log.Println(err)
			}
		case err := <-readErrChan:
			if err == io.EOF {
				if self.upload.Ready {
					self.upload.Data <- nil
					self.quit = true
					return nil
				}
				return errors.New("Connection dropped")
			} else {
				return err
			}
		case info := <-self.downloadQueue:
			self.InitiateDownload(info)
		case <-pingTicker.C:
			if self.mode == AGENT {
				self.Ping()
			}
		case <-reqTicker.C:
			err := self.ScanForTimeoutRequests()
			if self.reset {
				if err == nil {
					err = errors.New("reset request")
				}
				return err
			}
		}
	}
}

func (self *Ghost) RegisterTTY(session_id, ttyName string) {
	self.ttyName2Sid[ttyName] = session_id
}

func (self *Ghost) RegisterSession(session_id, pidStr string) {
	pid, err := strconv.Atoi(pidStr)
	if err != nil {
		panic(err)
	}
	self.terminalSid2Pid[session_id] = pid
}

func (self *Ghost) AddToDownloadQueue(ttyName, filename string) {
	self.downloadQueue <- DownloadInfo{ttyName, filename}
}

// Start listening to LAN discovery message.
func (self *Ghost) StartLanDiscovery() {
	log.Println("LAN discovery: started")
	buf := make([]byte, BUFSIZ)
	conn, err := net.ListenPacket("udp", fmt.Sprintf(":%d", OVERLORD_LD_PORT))
	if err != nil {
		log.Printf("LAN discovery: %s, abort\n", err)
		return
	}

	defer func() {
		conn.Close()
		log.Println("LAN discovery: stopped")
	}()

	for {
		conn.SetReadDeadline(time.Now().Add(READ_TIMEOUT * time.Second))
		n, remote, err := conn.ReadFrom(buf)

		if self.pauseLanDisc {
			log.Println("LAN discovery: paused")
			ticker := time.NewTicker(READ_TIMEOUT * time.Second)
		waitLoop:
			for {
				select {
				case <-ticker.C:
					if !self.pauseLanDisc {
						break waitLoop
					}
				}
			}
			log.Println("LAN discovery: resumed")
			continue
		}

		if err != nil {
			continue
		}

		// LAN discovery packet format: "OVERLOARD [host]:port"
		data := strings.Split(string(buf[:n]), " ")
		if data[0] != "OVERLORD" {
			continue
		}

		overlordAddrParts := strings.Split(data[1], ":")
		remoteAddrParts := strings.Split(remote.String(), ":")

		var remoteAddr string
		if strings.Trim(overlordAddrParts[0], " ") == "" {
			remoteAddr = remoteAddrParts[0] + ":" + overlordAddrParts[1]
		} else {
			remoteAddr = data[1]
		}

		if !self.ExistsInAddr(remoteAddr) {
			log.Printf("LAN discovery: got overlord address %s", remoteAddr)
			self.addrs = append(self.addrs, remoteAddr)
		}
	}
}

// ServeHTTP method for serving JSON-RPC over HTTP.
func (self *Ghost) ServeHTTP(w http.ResponseWriter, req *http.Request) {
	var conn, _, err = w.(http.Hijacker).Hijack()
	if err != nil {
		log.Print("rpc hijacking ", req.RemoteAddr, ": ", err.Error())
		return
	}
	io.WriteString(conn, "HTTP/1.1 200\n")
	io.WriteString(conn, "Content-Type: application/json-rpc\n\n")
	self.server.ServeCodec(jsonrpc.NewServerCodec(conn))
}

// Starts a local RPC server used for communication between ghost instances.
func (self *Ghost) StartRPCServer() {
	log.Println("RPC Server: started")

	ghostRPC := NewGhostRPC(self)
	self.server = rpc.NewServer()
	self.server.RegisterName("rpc", ghostRPC)

	http.Handle("/", self)
	err := http.ListenAndServe(fmt.Sprintf("localhost:%d", GHOST_RPC_PORT), nil)
	if err != nil {
		log.Fatalf("Unable to listen at prt %d: %s\n", GHOST_RPC_PORT, err)
	}
}

// ScanGateWay scans currenty netowrk gateway and add it into addrs if not
// already exist.
func (self *Ghost) ScanGateway() {
	if gateways, err := GetGateWayIP(); err == nil {
		for _, gw := range gateways {
			addr := fmt.Sprintf("%s:%d", gw, OVERLORD_PORT)
			if !self.ExistsInAddr(addr) {
				self.addrs = append(self.addrs, addr)
			}
		}
	}
}

// Bootstrap and start the client.
func (self *Ghost) Start(lanDisc bool, RPCServer bool) {
	log.Printf("%s started\n", ModeStr(self.mode))
	log.Printf("MID: %s\n", self.mid)
	log.Printf("SID: %s\n", self.sid)

	if lanDisc {
		go self.StartLanDiscovery()
	}

	if RPCServer {
		go self.StartRPCServer()
	}

	for {
		self.ScanGateway()
		err := self.Register()
		if err == nil {
			err = self.Listen()
		}
		if self.quit {
			break
		}
		log.Printf("%s, retrying in %ds\n", err, RETRY_INTERVAL)
		time.Sleep(RETRY_INTERVAL * time.Second)
		self.Reset()
	}
}

// Returns a GhostRPC client object which can be used to call GhostRPC methods.
func GhostRPCServer() (*rpc.Client, error) {
	conn, err := net.Dial("tcp", fmt.Sprintf("localhost:%d", GHOST_RPC_PORT))
	if err != nil {
		return nil, err
	}

	io.WriteString(conn, "GET / HTTP/1.1\n\n")
	_, err = http.ReadResponse(bufio.NewReader(conn), nil)
	if err == nil {
		return jsonrpc.NewClient(conn), nil
	}
	return nil, err
}

// Add a file to the download queue, which would be pickup by the ghost
// control channel instance and perform download.
func DownloadFile(filename string) {
	client, err := GhostRPCServer()
	if err != nil {
		log.Printf("error: %s\n", err)
		os.Exit(1)
	}

	var ttyName string
	var f *os.File

	absPath, err := filepath.Abs(filename)
	if err != nil {
		goto fail
	}

	_, err = os.Stat(absPath)
	if err != nil {
		goto fail
	}

	f, err = os.Open(absPath)
	if err != nil {
		goto fail
	}
	f.Close()

	ttyName, err = TtyName(os.Stdout)
	if err != nil {
		goto fail
	}

	err = client.Call("rpc.AddToDownloadQueue", []string{ttyName, absPath},
		&EmptyReply{})
	if err != nil {
		goto fail
	}
	os.Exit(0)

fail:
	log.Println(err)
	os.Exit(1)
}

func StartGhost(args []string, mid string, noLanDisc bool, noRPCServer bool,
	tlsCertFile string, enableTLSWithoutVerify bool, propFile string, download string,
	reset bool) {
	var addrs []string

	if reset {
		client, err := GhostRPCServer()
		if err != nil {
			log.Printf("error: %s\n", err)
			os.Exit(1)
		}

		err = client.Call("rpc.Reconnect", &EmptyArgs{}, &EmptyReply{})
		if err != nil {
			log.Printf("Reset: %s\n", err)
			os.Exit(1)
		}
		os.Exit(0)
	}

	if download != "" {
		DownloadFile(download)
	}

	if len(args) >= 1 {
		addrs = append(addrs, fmt.Sprintf("%s:%d", args[0], OVERLORD_PORT))
	}
	addrs = append(addrs, fmt.Sprintf("%s:%d", LOCALHOST, OVERLORD_PORT))

	tlsSettings := NewTLSSettings(tlsCertFile, enableTLSWithoutVerify)

	if propFile != "" {
		var err error
		propFile, err = filepath.Abs(propFile)
		if err != nil {
			log.Println("propFile:", err)
			os.Exit(1)
		}
	}

	g := NewGhost(addrs, tlsSettings, AGENT, mid)
	g.SetPropFile(propFile)
	go g.Start(!noLanDisc, !noRPCServer)

	ticker := time.NewTicker(time.Duration(60 * time.Second))

	for {
		select {
		case <-ticker.C:
			log.Printf("Num of Goroutines: %d\n", runtime.NumGoroutine())
		}
	}
}
