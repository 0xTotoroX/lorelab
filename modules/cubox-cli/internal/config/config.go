package config

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
)

type Config struct {
	Server string `json:"server"`
	Token  string `json:"token"`
}

func (c *Config) BaseURL() string {
	return "https://" + c.Server
}

func Dir() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", fmt.Errorf("cannot determine home directory: %w", err)
	}
	return filepath.Join(home, ".config", "cubox-cli"), nil
}

func Path() (string, error) {
	dir, err := Dir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, "config.json"), nil
}

// Load returns the effective configuration. Precedence (highest first):
//  1. Environment variables CUBOX_TOKEN / CUBOX_SERVER override individual
//     fields read from disk.
//  2. If the on-disk config is missing but both CUBOX_TOKEN and CUBOX_SERVER
//     are set, a transient Config is returned without touching disk. This
//     lets Agents/CI run without persisting the token.
//  3. Otherwise the on-disk config is used as-is.
func Load() (*Config, error) {
	envToken := os.Getenv("CUBOX_TOKEN")
	envServer := os.Getenv("CUBOX_SERVER")

	p, err := Path()
	if err != nil {
		return nil, err
	}
	data, err := os.ReadFile(p)
	if err != nil {
		if os.IsNotExist(err) {
			if envToken != "" && envServer != "" {
				return &Config{Server: envServer, Token: envToken}, nil
			}
			return nil, fmt.Errorf("not logged in. Run `cubox-cli auth login` first, or set CUBOX_TOKEN and CUBOX_SERVER environment variables")
		}
		return nil, fmt.Errorf("reading config: %w", err)
	}
	var cfg Config
	if err := json.Unmarshal(data, &cfg); err != nil {
		return nil, fmt.Errorf("parsing config: %w", err)
	}
	if envToken != "" {
		cfg.Token = envToken
	}
	if envServer != "" {
		cfg.Server = envServer
	}
	if cfg.Server == "" || cfg.Token == "" {
		return nil, fmt.Errorf("incomplete config. Run `cubox-cli auth login` to reconfigure")
	}
	return &cfg, nil
}

func Save(cfg *Config) error {
	dir, err := Dir()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(dir, 0700); err != nil {
		return fmt.Errorf("creating config dir: %w", err)
	}
	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return fmt.Errorf("marshalling config: %w", err)
	}
	p := filepath.Join(dir, "config.json")
	if err := os.WriteFile(p, data, 0600); err != nil {
		return fmt.Errorf("writing config: %w", err)
	}
	return nil
}

func Remove() error {
	p, err := Path()
	if err != nil {
		return err
	}
	if err := os.Remove(p); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("removing config: %w", err)
	}
	return nil
}

// LoadAppToken returns the Cubox.app login token used by the web/app API
// group (/c/api/* without the cli segment). Resolution order:
//
//  1. CUBOX_CTOKEN environment variable
//  2. macOS: read "Ctoken" from the Cubox.app group-container preferences
//     (available whenever the Cubox.app is logged in)
//
// Note: this token is separate from the API extension token (Token above).
// The web/app group requires it sent as a bare Authorization value.
func LoadAppToken() (string, error) {
	if t := os.Getenv("CUBOX_CTOKEN"); t != "" {
		return t, nil
	}
	if runtime.GOOS == "darwin" {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", err
		}
		plist := filepath.Join(home, "Library", "Group Containers",
			"group.com.guaiqi.cubox", "Library", "Preferences",
			"group.com.guaiqi.cubox.plist")
		out, err := exec.Command("defaults", "read", plist, "Ctoken").Output()
		if err == nil {
			if t := strings.TrimSpace(string(out)); t != "" {
				return t, nil
			}
		}
		return "", fmt.Errorf("Cubox app token not found. Log in to the Cubox.app, or set CUBOX_CTOKEN")
	}
	return "", fmt.Errorf("the web/app API group requires CUBOX_CTOKEN (Cubox.app login token) on this platform")
}
