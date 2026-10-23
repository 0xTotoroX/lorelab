package cmd

import (
	"fmt"

	"github.com/OLCUBO/cubox-cli/internal/config"
	"github.com/spf13/cobra"
)

var importCmd = &cobra.Command{
	Use:   "import",
	Short: "Import bookmarks through the official import task pipeline",
	Long: `Import a bookmarks export file (Netscape HTML, the same format the
Cubox web app's Preferences → Import accepts) through the official task
pipeline: upload the file, then poll the task progress.

Experimental: the multipart file field name is inferred from the app.
Folder structure inside the HTML file is preserved.`,
}

var importFile string

var importBookmarksCmd = &cobra.Command{
	Use:   "bookmarks",
	Short: "Upload a bookmarks export file (HTML) as an import task",
	Example: `  cubox-cli import bookmarks --file ~/Downloads/bookmarks.html`,
	RunE: func(cmd *cobra.Command, args []string) error {
		if importFile == "" {
			return fmt.Errorf("--file is required")
		}
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		raw, err := web.WebBookmarkImport(importFile)
		if err != nil {
			return err
		}
		printJSON(map[string]interface{}{
			"message": "import task submitted — poll with `cubox-cli import progress`",
			"data":    jsonRaw(raw),
		})
		return nil
	},
}

var importProgressCmd = &cobra.Command{
	Use:   "progress",
	Short: "Show the progress of the latest import task",
	RunE: func(cmd *cobra.Command, args []string) error {
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		web, err := webClient(cfg)
		if err != nil {
			return err
		}
		raw, err := web.WebImportProgress()
		if err != nil {
			return err
		}
		printJSON(jsonRaw(raw))
		return nil
	},
}

func init() {
	importCmd.AddCommand(importBookmarksCmd)
	importCmd.AddCommand(importProgressCmd)
	rootCmd.AddCommand(importCmd)

	importBookmarksCmd.Flags().StringVar(&importFile, "file", "", "path to the bookmarks HTML file (required)")
}
