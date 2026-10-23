// [INPUT]: Cobra flags, local ID files, config.Load, and Client.GetCardBatch.
// [OUTPUT]: card batch command; a stable JSON document even on partial failure.
// [POS]: Read-only card command, separate from card detail and batch mutations.
// [PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
package cmd

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"github.com/OLCUBO/cubox-cli/internal/client"
	"github.com/OLCUBO/cubox-cli/internal/config"
	"github.com/spf13/cobra"
)

func init() {
	cardCmd.AddCommand(newCardBatchCmd(func() (*client.Client, error) {
		cfg, err := config.Load()
		if err != nil {
			return nil, fmt.Errorf("cannot load Cubox configuration; check login or CUBOX_SERVER/CUBOX_TOKEN")
		}
		return client.New(cfg.BaseURL(), cfg.Token), nil
	}))
}

func newCardBatchCmd(newClient func() (*client.Client, error)) *cobra.Command {
	var ids []string
	var idsFile string
	var workers int
	cmd := &cobra.Command{
		Use:   "batch",
		Short: "Read card details in a bounded batch with ordered JSON results",
		Long: `Read card details using one shared Client with 500 ms request spacing.
IDs from --id precede --ids-file (one ID per line); duplicates are read once.
Workers default to 2 (range 1..4). Three consecutive completed errors stop new
requests; already admitted requests finish. No retries or original-site fetches.

Always outputs JSON, including with -o text; -o pretty indents it. A batch with
errors or skipped cards still writes the full result, then exits nonzero.
body_available means body text is present, not that the original post is complete.

Examples:
  cubox-cli card batch --id CARD1,CARD2 --workers 2
  cubox-cli card batch --ids-file card-ids.txt -o pretty`,
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			if workers < 1 || workers > 4 {
				return fmt.Errorf("workers must be between 1 and 4")
			}
			allIDs, err := readCardBatchIDs(ids, idsFile)
			if err != nil {
				return err
			}
			c, err := newClient()
			if err != nil {
				return err
			}
			batch, batchErr := c.GetCardBatch(cmd.Context(), allIDs, workers)
			if batch == nil {
				return batchErr
			}
			// Do not use printJSON: update notices must not wrap this contract.
			enc := json.NewEncoder(cmd.OutOrStdout())
			if outputFormat == "pretty" {
				enc.SetIndent("", "  ")
			}
			if err := enc.Encode(batch); err != nil {
				return fmt.Errorf("could not write card batch JSON")
			}
			return batchErr
		},
	}
	cmd.Flags().StringSliceVar(&ids, "id", nil, "card IDs (comma-separated; may be repeated)")
	cmd.Flags().StringVar(&idsFile, "ids-file", "", "UTF-8 file with one card ID per line")
	cmd.Flags().IntVar(&workers, "workers", 2, "concurrent workers (1..4); all share the request throttle")
	return cmd
}

func readCardBatchIDs(ids []string, path string) ([]string, error) {
	all := append([]string(nil), ids...)
	if path != "" {
		f, err := os.Open(path)
		if err != nil {
			return nil, fmt.Errorf("cannot open --ids-file")
		}
		defer f.Close()
		scanner := bufio.NewScanner(f)
		first := true
		for scanner.Scan() {
			line := scanner.Text()
			if first {
				line = strings.TrimPrefix(line, "\ufeff")
				first = false
			}
			if strings.Contains(line, ",") {
				return nil, fmt.Errorf("--ids-file must contain one card ID per line, not comma-separated lists")
			}
			all = append(all, line)
		}
		if scanner.Err() != nil {
			return nil, fmt.Errorf("cannot read --ids-file (maximum line size is 64 KiB)")
		}
	}
	all = client.NormalizeCardIDs(all)
	if len(all) == 0 {
		return nil, fmt.Errorf("provide at least one card ID with --id or --ids-file")
	}
	return all, nil
}
