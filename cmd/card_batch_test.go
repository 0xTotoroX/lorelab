package cmd

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/OLCUBO/cubox-cli/internal/client"
	"github.com/OLCUBO/cubox-cli/internal/update"
	"github.com/spf13/cobra"
)

func TestCardBatchIDInputs(t *testing.T) {
	path := filepath.Join(t.TempDir(), "ids.txt")
	if err := os.WriteFile(path, []byte("\ufeffb\r\na\r\n\r\n c \n"), 0600); err != nil {
		t.Fatal(err)
	}
	ids, err := readCardBatchIDs([]string{" a ", "b", "", "a"}, path)
	if err != nil || !reflect.DeepEqual(ids, []string{"a", "b", "c"}) {
		t.Fatalf("ids=%v err=%v", ids, err)
	}
	if ids, err = readCardBatchIDs(nil, path); err != nil || !reflect.DeepEqual(ids, []string{"b", "a", "c"}) {
		t.Fatalf("ids=%v err=%v", ids, err)
	}
	if _, err := readCardBatchIDs(nil, path+".missing"); err == nil {
		t.Fatal("missing file accepted")
	}
	if _, err := readCardBatchIDs(nil, ""); err == nil {
		t.Fatal("empty input accepted")
	}
	for _, content := range []string{"a,b\n", strings.Repeat("x", 70*1024), " \n\n"} {
		if err := os.WriteFile(path, []byte(content), 0600); err != nil {
			t.Fatal(err)
		}
		if _, err := readCardBatchIDs(nil, path); err == nil {
			t.Fatal("invalid file accepted")
		}
	}
}

func batchTestRoot(factory func() (*client.Client, error)) *cobra.Command {
	root := &cobra.Command{Use: "cubox-cli", SilenceErrors: true, SilenceUsage: true}
	root.PersistentFlags().StringVarP(&outputFormat, "output", "o", "json", "output format")
	card := &cobra.Command{Use: "card"}
	card.AddCommand(newCardBatchCmd(factory))
	root.AddCommand(card)
	return root
}

func TestCardBatchCLIJSONContract(t *testing.T) {
	oldFormat, oldInfo := outputFormat, updateInfo
	t.Cleanup(func() { outputFormat, updateInfo = oldFormat, oldInfo })
	updateInfo = &update.Info{Latest: "99.0.0", Message: "notice must not wrap batch"}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := r.URL.Query().Get("id")
		if id == "bad" {
			_, _ = io.WriteString(w, `{"code":-1000,"message":"secret token must not reach output"}`)
			return
		}
		card := client.CardDetail{ID: id, Content: "[social.example](https://social.example/post/1)\n\nnull\n\n[social.example](https://social.example/post/1)\n", Description: "A truncated excerpt…"}
		_ = json.NewEncoder(w).Encode(map[string]any{"code": 200, "data": card})
	}))
	defer server.Close()
	for _, format := range []string{"json", "pretty", "text"} {
		t.Run(format, func(t *testing.T) {
			created := 0
			root := batchTestRoot(func() (*client.Client, error) { created++; return client.New(server.URL, "test-token"), nil })
			var stdout, stderr bytes.Buffer
			root.SetOut(&stdout)
			root.SetErr(&stderr)
			root.SetArgs([]string{"card", "batch", "--id", "good,bad,good", "--id", "last", "-o", format})
			if err := root.Execute(); !errors.Is(err, client.ErrCardBatchIncomplete) {
				t.Fatalf("err=%v", err)
			}
			if created != 1 {
				t.Fatalf("created %d Clients", created)
			}
			var batch client.CardBatch
			decoder := json.NewDecoder(&stdout)
			if err := decoder.Decode(&batch); err != nil {
				t.Fatal(err)
			}
			if err := decoder.Decode(new(any)); !errors.Is(err, io.EOF) {
				t.Fatalf("extra stdout: %v", err)
			}
			if batch.SchemaVersion != 1 || batch.Kind != "cubox_card_batch" || batch.Counts != (client.CardBatchCounts{Total: 3, OK: 2, Error: 1}) {
				t.Fatalf("unexpected contract: %+v", batch)
			}
			if batch.Items[0].ID != "good" || batch.Items[1].ID != "bad" || batch.Items[2].ID != "last" {
				t.Fatal("wrong output order")
			}
			if *batch.Items[0].ContentStatus != "description_only" || batch.Items[0].Card.Description != "A truncated excerpt…" {
				t.Fatal("placeholder classified as body or original detail changed")
			}
			if batch.Items[1].ContentStatus != nil || batch.Items[1].Card != nil || batch.Items[1].Error.Code != "api_error" {
				t.Fatalf("bad error contract: %+v", batch.Items[1])
			}
		})
	}
}

func TestCardBatchCLIRejectsInputsBeforeConfig(t *testing.T) {
	oldFormat := outputFormat
	t.Cleanup(func() { outputFormat = oldFormat })
	for _, args := range [][]string{
		{}, {"--id", "a", "--workers", "0"}, {"--id", "a", "--workers", "5"},
		{"--ids-file", filepath.Join(t.TempDir(), "missing")}, {"--id", "a", "unexpected"},
	} {
		root := batchTestRoot(func() (*client.Client, error) {
			t.Error("configuration loaded for invalid input")
			return nil, errors.New("must not load")
		})
		root.SetArgs(append([]string{"card", "batch"}, args...))
		root.SetOut(io.Discard)
		root.SetErr(io.Discard)
		if err := root.Execute(); err == nil {
			t.Fatalf("accepted %v", args)
		}
	}
	cmd := newCardBatchCmd(nil)
	if got, _ := cmd.Flags().GetInt("workers"); got != 2 {
		t.Fatalf("default workers=%d", got)
	}
}

// Reuse Execute and Cobra in a subprocess to verify the exit boundary without
// loading any user config or starting the update notifier.
func TestCardBatchCLIProcessHelper(t *testing.T) {
	if os.Getenv("CUBOX_BATCH_TEST_HELPER") != "1" {
		return
	}
	rootCmd = batchTestRoot(func() (*client.Client, error) {
		return client.New(os.Getenv("CUBOX_BATCH_TEST_URL"), "test-token"), nil
	})
	args := os.Args
	for i, arg := range args {
		if arg == "--" {
			rootCmd.SetArgs(args[i+1:])
			break
		}
	}
	if err := Execute(); err != nil {
		os.Exit(1)
	}
	os.Exit(0)
}

func TestCardBatchCLIExitCodeAndStderr(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("id") == "bad" {
			w.WriteHeader(500)
			_, _ = io.WriteString(w, "test-token secret-response")
			return
		}
		_, _ = fmt.Fprintf(w, `{"code":200,"data":{"id":%q,"content":null}}`, r.URL.Query().Get("id"))
	}))
	defer server.Close()
	for _, tc := range []struct {
		ids  string
		exit int
	}{{"good", 0}, {"good,bad", 1}, {"bad", 1}} {
		process := exec.Command(os.Args[0], "-test.run=^TestCardBatchCLIProcessHelper$", "--", "card", "batch", "--id", tc.ids)
		process.Env = append(os.Environ(), "CUBOX_BATCH_TEST_HELPER=1", "CUBOX_BATCH_TEST_URL="+server.URL)
		var stdout, stderr bytes.Buffer
		process.Stdout, process.Stderr = &stdout, &stderr
		err := process.Run()
		if process.ProcessState.ExitCode() != tc.exit {
			t.Fatalf("exit=%v err=%v stderr=%s", process.ProcessState, err, stderr.String())
		}
		var batch client.CardBatch
		if err := json.Unmarshal(stdout.Bytes(), &batch); err != nil || batch.Kind != "cubox_card_batch" {
			t.Fatalf("stdout=%s err=%v", stdout.String(), err)
		}
		if strings.Contains(stdout.String()+stderr.String(), "test-token") || strings.Contains(stdout.String()+stderr.String(), "secret-response") {
			t.Fatal("credentials or server error leaked")
		}
		if tc.exit == 1 {
			var envelope map[string]any
			if err := json.Unmarshal(stderr.Bytes(), &envelope); err != nil || envelope["error"] == nil {
				t.Fatalf("stderr=%s err=%v", stderr.String(), err)
			}
		}
		for _, item := range batch.Items {
			if item.Status == "ok" && *item.ContentStatus != "empty" {
				t.Fatal("JSON null became a body")
			}
		}
	}
}
