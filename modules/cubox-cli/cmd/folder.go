package cmd

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/OLCUBO/cubox-cli/internal/client"
	"github.com/OLCUBO/cubox-cli/internal/config"
	"github.com/spf13/cobra"
)

var folderCmd = &cobra.Command{
	Use:   "folder",
	Short: "Manage folders",
}

var folderListCmd = &cobra.Command{
	Use:   "list",
	Short: "List all folders",
	RunE:  runFolderList,
}

// ---- folder delete ----

var (
	delIDs    []string
	delDryRun bool
	delHard   bool
)

var folderDeleteCmd = &cobra.Command{
	Use:   "delete",
	Short: "Delete one or more folders (batch)",
	Long: `Delete folders by ID.

Safety model:
  - Default (safe) mode first moves any remaining cards to Uncategorized and
    then deletes the folder — mirroring the Cubox app's "move cards to
    Uncategorized" delete option. Cards are never lost. Empty folders are
    unaffected by the move step.
  - --hard uses the direct delete endpoint instead (no card preservation).
    Only use it when you are certain the folders are empty.
  - --dry-run only shows which folders would be deleted.

These commands talk to the web/app API group and require the Cubox.app login
token (auto-read from the Cubox.app on macOS, or set CUBOX_CTOKEN).`,
	RunE: runFolderDelete,
}

// ---- folder new ----

var (
	newName   string
	newParent string
)

var folderNewCmd = &cobra.Command{
	Use:   "new",
	Short: "Create a folder",
	Long: `Create a folder.

Examples:
  cubox-cli folder new --name "Reading List"
  cubox-cli folder new --name "Sub Folder" --parent 7230156249357091393`,
	RunE: runFolderNew,
}

// ---- folder rename ----

var (
	renameID      string
	renameNewName string
)

var folderRenameCmd = &cobra.Command{
	Use:   "rename",
	Short: "Rename a folder",
	Example: `  cubox-cli folder rename --id 7230156249357091393 --new-name "New Name"`,
	RunE: runFolderRename,
}

// ---- folder archive ----

var (
	archIDs []string
	archOn  bool
	archOff bool
)

var folderArchiveCmd = &cobra.Command{
	Use:   "archive",
	Short: "Archive or unarchive folders",
	Long: `Archive or unarchive folders by ID.

Archiving a folder also archives all cards and sub-folders inside it
(the Cubox app applies the same cascade). Provide exactly one of
--on / --off.`,
	RunE: runFolderArchive,
}

func runFolderArchive(cmd *cobra.Command, args []string) error {
	if len(archIDs) == 0 {
		return fmt.Errorf("--id is required")
	}
	if archOn == archOff {
		return fmt.Errorf("provide exactly one of --on / --off")
	}
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	web, err := webClient(cfg)
	if err != nil {
		return err
	}
	if err := refuseIfSystemGroup(web, archIDs...); err != nil {
		return err
	}
	groups, err := web.WebListGroups()
	if err != nil {
		return err
	}
	byID := make(map[string]client.WebGroup, len(groups))
	for _, g := range groups {
		byID[g.GroupID] = g
	}

	type result struct {
		ID      string `json:"id"`
		Name    string `json:"name"`
		OK      bool   `json:"ok"`
		Message string `json:"message,omitempty"`
	}
	var results []result
	okCount := 0
	for _, id := range archIDs {
		name := "(unknown)"
		if g, found := byID[id]; found {
			name = g.GroupName
		}
		raw, err := web.WebArchiveFolder(id, archOn)
		_ = raw
		if err != nil {
			_, msg := parseAPIError(err)
			results = append(results, result{ID: id, Name: name, OK: false, Message: msg})
			continue
		}
		okCount++
		results = append(results, result{ID: id, Name: name, OK: true})
	}
	printJSON(map[string]interface{}{
		"count":   okCount,
		"total":   len(archIDs),
		"mode":    map[bool]string{true: "archive", false: "unarchive"}[archOn],
		"results": results,
	})
	return nil
}

// ---- folder move ----

var (
	moveID    string
	movePar   string
	moveIndex int
)

var folderMoveCmd = &cobra.Command{
	Use:   "move",
	Short: "Move a folder under another parent (and/or reorder)",
	Long: `Move a folder to a new parent, optionally at a specific index
among the siblings (0-based, default: last).

Implemented with the same endpoint the web app submits on drag & drop
(POST /c/api/group/move/another): two order snapshots (fromGroups for the
old siblings when moving across parents, toGroups for the new order under
the destination parent) are built from the live tree.`,
	Example: `  cubox-cli folder move --id 7230156249357091393 --parent 7507723518969122078
  cubox-cli folder move --id 7230156249357091393 --parent 7507723518969122078 --index 0`,
	RunE: runFolderMove,
}

func runFolderMove(cmd *cobra.Command, args []string) error {
	if moveID == "" {
		return fmt.Errorf("--id is required")
	}
	// --parent empty = move to root level (via move/another with a JSON-null
	// parentGroupId — verified live on the 187 test account 2026-10-14).
	// moveIndex < 0 means "append last" — no explicit validation needed.
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	web, err := webClient(cfg)
	if err != nil {
		return err
	}
	groups, err := web.WebListGroups()
	if err != nil {
		return err
	}
	byID := make(map[string]client.WebGroup, len(groups))
	kids := map[string][]client.WebGroup{}
	for _, g := range groups {
		byID[g.GroupID] = g
		p := ""
		if g.ParentGroupID != nil {
			p = *g.ParentGroupID
		}
		kids[p] = append(kids[p], g)
	}
	if err := refuseIfSystemGroup(web, moveID); err != nil {
		return err
	}
	x, found := byID[moveID]
	if !found {
		return fmt.Errorf("folder %s does not exist", moveID)
	}
	if movePar != "" {
		if _, dst := byID[movePar]; !dst {
			return fmt.Errorf("destination parent %s does not exist", movePar)
		}
	}
	oldParent := ""
	if x.ParentGroupID != nil {
		oldParent = *x.ParentGroupID
	}

	// Root-level move: move/another with a JSON-null parentGroupId
	// (verified live). update cannot do this: omitting the field is a pure
	// rename, and an EMPTY parentGroupId DELETES the group (verified!).
	if movePar == "" && moveIndex < 0 {
		if err := refuseIfSystemGroup(web, moveID); err != nil {
			return err
		}
		to := []map[string]interface{}{{"groupId": moveID, "parentGroupId": nil}}
		tb, _ := json.Marshal(to)
		raw, err := web.WebMoveFolderAnother("", string(tb))
		if err != nil {
			return err
		}
		printJSON(map[string]interface{}{
			"message": "folder moved to root level",
			"id":      moveID,
			"parent":  nil,
			"data":    jsonRaw(raw),
		})
		return nil
	}

	// Fast path: when no explicit position is requested, move via
	// /c/api/group/update — it accepts parentGroupId alongside groupName
	// (verified live) and is far simpler than the drag-snapshot endpoint.
	if moveIndex < 0 {
		raw, err := web.WebUpdateFolder(moveID, x.GroupName, movePar)
		if err != nil {
			return err
		}
		printJSON(map[string]interface{}{
			"message": "folder moved",
			"id":      moveID,
			"name":    x.GroupName,
			"parent":  movePar,
			"data":    jsonRaw(raw),
		})
		return nil
	}

	// toGroups: destination siblings minus X, with X inserted at moveIndex.
	to := make([]map[string]string, 0, len(kids[movePar])+1)
	pos := 0
	for _, k := range kids[movePar] {
		if k.GroupID == moveID {
			continue
		}
		if pos == moveIndex {
			to = append(to, map[string]string{"groupId": moveID, "parentGroupId": movePar})
			pos++
		}
		to = append(to, map[string]string{"groupId": k.GroupID, "parentGroupId": movePar})
		pos++
	}
	if pos == moveIndex {
		to = append(to, map[string]string{"groupId": moveID, "parentGroupId": movePar})
	}

	// fromGroups: old siblings minus X (only when moving across parents).
	fromJSON := ""
	if oldParent != movePar {
		from := make([]map[string]string, 0, len(kids[oldParent]))
		for _, k := range kids[oldParent] {
			if k.GroupID == moveID {
				continue
			}
			from = append(from, map[string]string{"groupId": k.GroupID, "parentGroupId": oldParent})
		}
		if len(from) > 0 {
			b, _ := json.Marshal(from)
			fromJSON = string(b)
		}
	}
	tb, _ := json.Marshal(to)

	raw, err := web.WebMoveFolderAnother(fromJSON, string(tb))
	if err != nil {
		return err
	}

	// Verify the move took effect.
	after, err := web.WebListGroups()
	if err != nil {
		return err
	}
	moved := false
	for _, g := range after {
		if g.GroupID == moveID && g.ParentGroupID != nil && *g.ParentGroupID == movePar {
			moved = true
		}
	}
	printJSON(map[string]interface{}{
		"message": map[bool]string{true: "folder moved", false: "move submitted but verification could not confirm the new parent"}[moved],
		"id":      moveID,
		"name":    x.GroupName,
		"parent":  movePar,
		"data":    jsonRaw(raw),
	})
	return nil
}

func init() {
	folderCmd.AddCommand(folderListCmd)
	folderCmd.AddCommand(folderDeleteCmd)
	folderCmd.AddCommand(folderNewCmd)
	folderCmd.AddCommand(folderRenameCmd)
	folderCmd.AddCommand(folderArchiveCmd)
	folderCmd.AddCommand(folderMoveCmd)
	rootCmd.AddCommand(folderCmd)

	folderArchiveCmd.Flags().StringSliceVar(&archIDs, "id", nil, "folder IDs to archive/unarchive (comma-separated, required)")
	folderArchiveCmd.Flags().BoolVar(&archOn, "on", false, "archive the folders")
	folderArchiveCmd.Flags().BoolVar(&archOff, "off", false, "unarchive the folders")

	folderMoveCmd.Flags().StringVar(&moveID, "id", "", "folder ID to move (required)")
	folderMoveCmd.Flags().StringVar(&movePar, "parent", "", "destination parent folder ID (required)")
	folderMoveCmd.Flags().IntVar(&moveIndex, "index", -1, "position among destination siblings (0-based, default: last)")

	folderDeleteCmd.Flags().StringSliceVar(&delIDs, "id", nil, "folder IDs to delete (comma-separated, required)")
	folderDeleteCmd.Flags().BoolVar(&delDryRun, "dry-run", false, "show what would be deleted without deleting")
	folderDeleteCmd.Flags().BoolVar(&delHard, "hard", false, "direct delete without moving remaining cards to Uncategorized")
	_ = folderDeleteCmd.MarkFlagRequired("id")

	folderNewCmd.Flags().StringVar(&newName, "name", "", "new folder name (required)")
	folderNewCmd.Flags().StringVar(&newParent, "parent", "", "parent folder ID (optional, root-level if omitted)")
	_ = folderNewCmd.MarkFlagRequired("name")

	folderRenameCmd.Flags().StringVar(&renameID, "id", "", "folder ID to rename (required)")
	folderRenameCmd.Flags().StringVar(&renameNewName, "new-name", "", "new folder name (required)")
	_ = folderRenameCmd.MarkFlagRequired("id")
	_ = folderRenameCmd.MarkFlagRequired("new-name")
}

func runFolderList(cmd *cobra.Command, args []string) error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	c := client.New(cfg.BaseURL(), cfg.Token)
	folders, err := c.ListFolders()
	if err != nil {
		return err
	}

	if outputFormat == "text" {
		printFoldersText(folders)
		return nil
	}
	printJSON(folders)
	return nil
}

// webClient returns a client bound to the Cubox.app login token for the
// web/app API group (/c/api/* without the cli segment).
func webClient(cfg *config.Config) (*client.Client, error) {
	appToken, err := config.LoadAppToken()
	if err != nil {
		return nil, err
	}
	return client.New(cfg.BaseURL(), appToken), nil
}

// systemGroupID returns the account's protected system group id (the
// "Uncategorized" / collection box, the group with an empty name). Operating
// on it (delete/rename/move/archive) corrupts the server-side group tree —
// this guard exists because exactly that happened on 2026-10-09 and required
// official server-side repair.
func systemGroupID(web *client.Client) (string, error) {
	groups, err := web.WebListGroups()
	if err != nil {
		return "", err
	}
	for _, g := range groups {
		if g.GroupName == "" {
			return g.GroupID, nil
		}
	}
	return "", nil
}

// refuseIfSystemGroup aborts with an explanation when any target is the
// protected system group.
func refuseIfSystemGroup(web *client.Client, ids ...string) error {
	sysID, err := systemGroupID(web)
	if err != nil || sysID == "" {
		return err // unresolvable → do not block on it, the loop below still guards per-id
	}
	for _, id := range ids {
		if id == sysID {
			return fmt.Errorf("refusing to operate on the system 'Uncategorized' group (%s): the server requires it; removing it corrupts the account group tree (incident 2026-10-09). If you really need this, ask Cubox support first", id)
		}
	}
	return nil
}

// ensureFolderPath resolves or creates a "a/b/c" folder path in the web/app
// group, returning the leaf folder ID. Existing folders are matched by name
// under each parent level; missing levels are created.
func ensureFolderPath(web *client.Client, path string) (string, error) {
	var parentID string
	for _, seg := range strings.Split(path, "/") {
		seg = strings.TrimSpace(seg)
		if seg == "" {
			return "", fmt.Errorf("empty path segment in folder path %q", path)
		}
		groups, err := web.WebListGroups()
		if err != nil {
			return "", err
		}
		found := ""
		for _, g := range groups {
			gp := ""
			if g.ParentGroupID != nil {
				gp = *g.ParentGroupID
			}
			if g.GroupName == seg && gp == parentID {
				found = g.GroupID
				break
			}
		}
		if found == "" {
			if _, err := web.WebCreateFolder(seg, parentID); err != nil {
				return "", fmt.Errorf("creating folder %q: %w", seg, err)
			}
			groups, err = web.WebListGroups()
			if err != nil {
				return "", err
			}
			for _, g := range groups {
				gp := ""
				if g.ParentGroupID != nil {
					gp = *g.ParentGroupID
				}
				if g.GroupName == seg && gp == parentID {
					found = g.GroupID
					break
				}
			}
			if found == "" {
				return "", fmt.Errorf("folder %q created but not found afterwards", seg)
			}
		}
		parentID = found
	}
	return parentID, nil
}

func runFolderDelete(cmd *cobra.Command, args []string) error {
	if len(delIDs) == 0 {
		return fmt.Errorf("--id is required")
	}
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	web, err := webClient(cfg)
	if err != nil {
		return err
	}

	// Resolve names for the report via the web group list.
	groups, err := web.WebListGroups()
	if err != nil {
		return err
	}
	byID := make(map[string]client.WebGroup, len(groups))
	for _, g := range groups {
		byID[g.GroupID] = g
	}

	if err := refuseIfSystemGroup(web, delIDs...); err != nil {
		return err
	}

	type result struct {
		ID      string `json:"id"`
		Name    string `json:"name"`
		OK      bool   `json:"ok"`
		Code    int    `json:"code,omitempty"`
		Message string `json:"message,omitempty"`
	}
	results := make([]result, 0, len(delIDs))
	missing := 0

	if delDryRun {
		for _, id := range delIDs {
			g, found := byID[id]
			if !found {
				results = append(results, result{ID: id, Name: "(not found)", OK: false, Message: "folder does not exist"})
				missing++
				continue
			}
			mode := "safe (move cards to Uncategorized, then delete)"
			if delHard {
				mode = "hard (direct delete)"
			}
			results = append(results, result{ID: id, Name: g.GroupName, OK: true, Message: "would delete: " + mode})
		}
		printJSON(map[string]interface{}{"dry_run": true, "count": len(delIDs) - missing, "results": results})
		return nil
	}

	okCount := 0
	for _, id := range delIDs {
		name := "(unknown)"
		if g, found := byID[id]; found {
			name = g.GroupName
		}
		var raw json.RawMessage
		var delErr error
		if delHard {
			raw, delErr = web.WebDeleteFolder(id)
		} else {
			raw, delErr = web.WebMoveFolderCardsOut(id)
		}
		_ = raw
		if delErr != nil {
			code, msg := parseAPIError(delErr)
			results = append(results, result{ID: id, Name: name, OK: false, Code: code, Message: msg})
			fmt.Fprintf(cmd.ErrOrStderr(), "failed: %s (%s): %s\n", name, id, msg)
			continue
		}
		okCount++
		results = append(results, result{ID: id, Name: name, OK: true})
	}

	printJSON(map[string]interface{}{
		"count":   okCount,
		"total":   len(delIDs),
		"mode":    map[bool]string{true: "hard", false: "safe"}[delHard],
		"results": results,
	})
	return nil
}

func runFolderNew(cmd *cobra.Command, args []string) error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	web, err := webClient(cfg)
	if err != nil {
		return err
	}
	// Nested path support: "a/b" creates (or reuses) a under root, then b
	// under a — the server has no path semantics of its own.
	if strings.Contains(newName, "/") {
		leaf, err := ensureFolderPath(web, newName)
		if err != nil {
			return err
		}
		printJSON(map[string]interface{}{"message": "folder path ensured", "name": newName, "id": leaf})
		return nil
	}
	raw, err := web.WebCreateFolder(newName, newParent)
	if err != nil {
		return err
	}
	printJSON(map[string]interface{}{"message": "folder created", "name": newName, "data": raw})
	return nil
}

func runFolderRename(cmd *cobra.Command, args []string) error {
	if strings.Contains(renameNewName, "/") {
		return fmt.Errorf("folder name must not contain '/'")
	}
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	web, err := webClient(cfg)
	if err != nil {
		return err
	}
	if err := refuseIfSystemGroup(web, renameID); err != nil {
		return err
	}
	raw, err := web.WebUpdateFolder(renameID, renameNewName, "")
	if err != nil {
		return err
	}
	printJSON(map[string]interface{}{"message": "folder renamed", "id": renameID, "name": renameNewName, "data": raw})
	return nil
}

func printFoldersText(folders []client.Folder) {
	for _, f := range folders {
		depth := strings.Count(f.NestedName, "/")
		indent := strings.Repeat("  ", depth)
		label := f.Name
		if f.Uncategorized {
			label += " (uncategorized)"
		}
		fmt.Printf("%s%s  [%s]\n", indent, label, f.ID)
	}
}

// parseAPIError extracts code and message from an "API error %d: %s" error.
func parseAPIError(err error) (int, string) {
	msg := err.Error()
	var code int
	if _, scanErr := fmt.Sscanf(msg, "API error %d:", &code); scanErr == nil {
		if idx := strings.Index(msg, ": "); idx != -1 {
			return code, msg[idx+2:]
		}
	}
	return -1, msg
}
