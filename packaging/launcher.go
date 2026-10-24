// [INPUT]: 同名 .exe.json 配置和原始 argv。
// [OUTPUT]: 不经过 shell 的原生 Windows CLI 转交，保留参数和退出码。
// [POS]: 四个独立入口共用的小型启动器；配置由安装器生成。
// [PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
)

type configuration struct {
	Command     []string          `json:"command"`
	Environment map[string]string `json:"environment"`
}

func main() {
	path, err := os.Executable()
	if err != nil {
		fail(err)
	}
	data, err := os.ReadFile(path + ".json")
	if err != nil {
		fail(err)
	}
	var config configuration
	if err := json.Unmarshal(data, &config); err != nil {
		fail(err)
	}
	if len(config.Command) == 0 {
		fail(fmt.Errorf("missing managed command"))
	}
	os.Unsetenv("PYTHONPATH")
	os.Unsetenv("PYTHONHOME")
	for key, value := range config.Environment {
		os.Setenv(key, value)
	}
	command := exec.Command(config.Command[0], append(config.Command[1:], os.Args[1:]...)...)
	command.Stdin, command.Stdout, command.Stderr = os.Stdin, os.Stdout, os.Stderr
	if err := command.Run(); err != nil {
		if exit, ok := err.(*exec.ExitError); ok {
			os.Exit(exit.ExitCode())
		}
		fail(err)
	}
}

func fail(err error) { fmt.Fprintln(os.Stderr, "LoreLab:", err); os.Exit(1) }
