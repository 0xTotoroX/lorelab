package cmd

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/OLCUBO/cubox-cli/internal/client"
	"github.com/OLCUBO/cubox-cli/internal/tagcleanup"
)

type pruneStore struct {
	tags         []client.Tag
	active       map[string]client.CardDetail
	archived     map[string]client.CardDetail
	deletedTags  []string
	deletedIDs   []string
	filterCalls  map[string]int
	addOnRecheck bool
	failFilter   bool
	listCalls    int
	detailCalls  int
}

func (s *pruneStore) ListTags() ([]client.Tag, error) {
	s.listCalls++
	return append([]client.Tag(nil), s.tags...), nil
}

func (s *pruneStore) GetCardDetail(id string) (*client.CardDetail, error) {
	s.detailCalls++
	if card, ok := s.active[id]; ok {
		return &card, nil
	}
	if card, ok := s.archived[id]; ok {
		return &card, nil
	}
	return nil, fmt.Errorf("card not found")
}

func (s *pruneStore) DeleteCards(ids []string) error {
	s.deletedIDs = append(s.deletedIDs, ids...)
	for _, id := range ids {
		delete(s.active, id)
		delete(s.archived, id)
	}
	return nil
}

func (s *pruneStore) FilterCards(req *client.CardFilterRequest) ([]client.Card, error) {
	if s.failFilter {
		return nil, fmt.Errorf("simulated filter failure")
	}
	id := req.TagFilters[0]
	s.filterCalls[id]++
	if s.addOnRecheck && id == "picsed" && s.filterCalls[id] >= 3 && !*req.Archived {
		return []client.Card{{ID: "new"}}, nil
	}
	name := ""
	for _, tag := range s.tags {
		if tag.ID == id {
			name = tag.NestedName
		}
	}
	cards := s.active
	if *req.Archived {
		cards = s.archived
	}
	ids := make([]string, 0, len(cards))
	for id := range cards {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	result := []client.Card{}
	for _, cardID := range ids {
		if cardID <= req.LastCardID {
			continue
		}
		card := cards[cardID]
		for _, tag := range card.Tags {
			if tag == name {
				result = append(result, client.Card{ID: card.ID})
				if len(result) == req.Limit {
					return result, nil
				}
			}
		}
	}
	return result, nil
}

func (s *pruneStore) DeleteTags(ids []string) error {
	s.deletedTags = append(s.deletedTags, ids...)
	kept := s.tags[:0]
	for _, tag := range s.tags {
		if tag.ID != ids[0] {
			kept = append(kept, tag)
		}
	}
	s.tags = kept
	return nil
}

func pruneFixture() *pruneStore {
	root := "parent"
	topicRoot := "topic-root"
	processingRoot := "processing-root"
	return &pruneStore{
		tags: []client.Tag{
			{ID: "picsed", Name: "PICSED", NestedName: "PICSED"},
			{ID: "source", Name: "来源", NestedName: "来源"},
			{ID: "keep", Name: "留存标签", NestedName: "留存标签"},
			{ID: "archive", Name: "归档标签", NestedName: "归档标签"},
			{ID: root, Name: "父标签", NestedName: "父标签"},
			{ID: "child", Name: "子标签", NestedName: "父标签/子标签", ParentID: &root},
			{ID: "unrelated", Name: "其他空标签", NestedName: "其他空标签"},
			{ID: topicRoot, Name: "主题", NestedName: "主题"},
			{ID: "rag", Name: "RAG", NestedName: "主题/RAG", ParentID: &topicRoot},
			{ID: processingRoot, Name: "处理", NestedName: "处理"},
			{ID: "todo", Name: "00 待审", NestedName: "处理/00 待审", ParentID: &processingRoot},
		},
		active: map[string]client.CardDetail{
			"a": {ID: "a", Tags: []string{"PICSED", "来源", "留存标签", "归档标签", "父标签", "主题/RAG", "处理/00 待审"}},
			"b": {ID: "b", Tags: []string{"PICSED"}},
			"c": {ID: "c", Tags: []string{"留存标签"}},
		},
		archived: map[string]client.CardDetail{
			"z": {ID: "z", Tags: []string{"归档标签"}},
		},
		filterCalls: map[string]int{},
	}
}

func TestDeleteAutomaticallyPrunesOnlyAffectedEmptyLeafTag(t *testing.T) {
	store := pruneFixture()
	report, err := deleteCardsAndPrune(context.Background(), store, []string{"a", "b"}, false)
	if err != nil || !report.CardDeleted || len(report.Tags.Deleted) != 1 ||
		report.Tags.Deleted[0].Name != "PICSED" || len(store.deletedTags) != 1 ||
		store.deletedTags[0] != "picsed" || store.filterCalls["picsed"] != 4 {
		t.Fatalf("unexpected cleanup: report=%+v deleted=%v err=%v", report, store.deletedTags, err)
	}
	if len(report.Tags.Skipped) != 4 || len(store.active) != 1 || len(store.archived) != 1 {
		t.Fatalf("occupied/protected/parent tags were not kept: report=%+v", report)
	}
	for _, name := range []string{"来源", "留存标签", "归档标签", "父标签", "其他空标签", "主题/RAG", "处理/00 待审"} {
		found := false
		for _, tag := range store.tags {
			found = found || tag.NestedName == name
		}
		if !found {
			t.Fatalf("unrelated or occupied tag %s was deleted", name)
		}
	}
	t.Logf("deleted cards=%v; deleted tags=%v; skipped=%v", store.deletedIDs, report.Tags.Deleted, report.Tags.Skipped)
}

func TestManualPrunePreviewAndApplyExistingEmptyTag(t *testing.T) {
	store := pruneFixture()
	delete(store.active, "a")
	delete(store.active, "b")
	preview, err := tagcleanup.Prune(context.Background(), store, []string{"picsed"}, false)
	if err != nil || len(preview.Eligible) != 1 || len(preview.Deleted) != 0 || len(store.deletedTags) != 0 {
		t.Fatalf("preview changed tags: %+v %v", preview, err)
	}
	result, err := tagcleanup.Prune(context.Background(), store, []string{"picsed"}, true)
	if err != nil || len(result.Deleted) != 1 || len(store.deletedTags) != 1 {
		t.Fatalf("manual prune failed: %+v %v", result, err)
	}
}

func TestDeleteDryRunPredictsOnlyTagsThatWouldBecomeEmpty(t *testing.T) {
	store := pruneFixture()
	tags, err := store.ListTags()
	if err != nil {
		t.Fatal(err)
	}
	affected, err := tagcleanup.AffectedTags(store, tags, []string{"a", "b"})
	if err != nil {
		t.Fatal(err)
	}
	report, err := tagcleanup.PreviewAfterDelete(context.Background(), store, tags, affected, []string{"a", "b"})
	if err != nil || len(report.Eligible) != 1 || report.Eligible[0].Name != "PICSED" ||
		len(report.Skipped) != 4 || len(store.deletedIDs) != 0 || len(store.deletedTags) != 0 {
		t.Fatalf("dry-run prediction was wrong or wrote data: %+v %v", report, err)
	}
}

func TestDeleteDryRunFindsSurvivorAfterPageOfDeletedCards(t *testing.T) {
	store := &pruneStore{
		tags:   []client.Tag{{ID: "picsed", Name: "PICSED", NestedName: "PICSED"}},
		active: map[string]client.CardDetail{}, archived: map[string]client.CardDetail{},
		filterCalls: map[string]int{},
	}
	deleting := []string{}
	for i := 0; i < 50; i++ {
		id := fmt.Sprintf("a%02d", i)
		store.active[id] = client.CardDetail{ID: id, Tags: []string{"PICSED"}}
		deleting = append(deleting, id)
	}
	store.active["z"] = client.CardDetail{ID: "z", Tags: []string{"PICSED"}}
	report, err := tagcleanup.PreviewAfterDelete(context.Background(), store, store.tags, []string{"picsed"}, deleting)
	if err != nil || len(report.Eligible) != 0 || len(report.Skipped) != 1 ||
		report.Skipped[0].Reason != "active cards remain" || store.filterCalls["picsed"] != 2 {
		t.Fatalf("survivor after first page was missed: %+v %v", report, err)
	}
}

func TestDeleteCanKeepEmptyTags(t *testing.T) {
	store := pruneFixture()
	report, err := deleteCardsAndPrune(context.Background(), store, []string{"a", "b"}, true)
	if err != nil || !report.CardDeleted || len(store.deletedTags) != 0 || store.listCalls != 0 || store.detailCalls != 0 {
		t.Fatalf("keep-empty-tags still inspected or deleted tags: %+v %v", report, err)
	}
}

func TestDeletePreflightFailureDoesNotDeleteCards(t *testing.T) {
	store := pruneFixture()
	report, err := deleteCardsAndPrune(context.Background(), store, []string{"missing"}, false)
	if err == nil || report.CardDeleted || len(store.deletedIDs) != 0 || len(store.deletedTags) != 0 {
		t.Fatalf("preflight failure deleted data: %+v %v", report, err)
	}
}

func TestPruneRechecksBeforeDeleting(t *testing.T) {
	store := pruneFixture()
	delete(store.active, "a")
	delete(store.active, "b")
	store.addOnRecheck = true
	report, err := tagcleanup.Prune(context.Background(), store, []string{"picsed"}, true)
	if err != nil || len(report.Deleted) != 0 || len(report.Skipped) != 1 ||
		!strings.Contains(report.Skipped[0].Reason, "changed before deletion") || len(store.deletedTags) != 0 {
		t.Fatalf("changed occupancy was ignored: %+v %v", report, err)
	}
}

func TestDeleteReportsCleanupFailureAfterCardDeletion(t *testing.T) {
	store := pruneFixture()
	store.failFilter = true
	report, err := deleteCardsAndPrune(context.Background(), store, []string{"a", "b"}, false)
	if err == nil || !report.CardDeleted || len(store.deletedIDs) != 2 || len(store.deletedTags) != 0 {
		t.Fatalf("cleanup failure hidden: %+v %v", report, err)
	}
}

func TestResolveAlreadyEmptyTagByExactName(t *testing.T) {
	store := pruneFixture()
	id, err := resolvePruneTagID(store.tags, "PICSED")
	if err != nil || id != "picsed" {
		t.Fatalf("PICSED did not resolve: %s %v", id, err)
	}
	if _, err := resolvePruneTagID(store.tags, "PIC"); err == nil {
		t.Fatal("partial tag name matched")
	}
}

func TestDeletePrunesEmptySourceChildButKeepsSourceRoot(t *testing.T) {
	root := "source"
	store := &pruneStore{
		tags: []client.Tag{
			{ID: root, Name: "来源", NestedName: "来源"},
			{ID: "picsed", Name: "PICSED", NestedName: "来源/PICSED", ParentID: &root},
		},
		active:   map[string]client.CardDetail{"a": {ID: "a", Tags: []string{"来源/PICSED"}}},
		archived: map[string]client.CardDetail{}, filterCalls: map[string]int{},
	}
	report, err := deleteCardsAndPrune(context.Background(), store, []string{"a"}, false)
	if err != nil || len(report.Tags.Deleted) != 1 || report.Tags.Deleted[0].Name != "来源/PICSED" ||
		len(store.tags) != 1 || store.tags[0].ID != root {
		t.Fatalf("source child cleanup changed the root or failed: %+v %v", report, err)
	}
}

// Capture actual serialized output, including large batches without pipe limits.
func captureDeleteDryRun(t *testing.T, c *client.Client, ids []string, format string) (string, string) {
	t.Helper()
	oldOut, oldErr, oldFormat, oldInfo := os.Stdout, os.Stderr, outputFormat, updateInfo
	stdout, err := os.Create(filepath.Join(t.TempDir(), "stdout"))
	if err != nil {
		t.Fatal(err)
	}
	defer stdout.Close()
	stderr, err := os.Create(filepath.Join(t.TempDir(), "stderr"))
	if err != nil {
		t.Fatal(err)
	}
	defer stderr.Close()
	os.Stdout, os.Stderr, outputFormat, updateInfo = stdout, stderr, format, nil
	defer func() { os.Stdout, os.Stderr, outputFormat, updateInfo = oldOut, oldErr, oldFormat, oldInfo }()
	if err := outputDryRun(context.Background(), c, ids, true); err != nil {
		t.Fatal(err)
	}
	out, err := os.ReadFile(stdout.Name())
	if err != nil {
		t.Fatal(err)
	}
	log, err := os.ReadFile(stderr.Name())
	if err != nil {
		t.Fatal(err)
	}
	return string(out), string(log)
}

func TestDeleteDryRunLargeJSONListsExactIDsWithoutRequests(t *testing.T) {
	for _, count := range []int{4, 4096} {
		t.Run(fmt.Sprint(count), func(t *testing.T) {
			var requests atomic.Int32
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				requests.Add(1)
				http.Error(w, "dry-run must not call any endpoint", http.StatusInternalServerError)
			}))
			defer server.Close()
			ids := make([]string, count)
			for i := range ids {
				ids[i] = fmt.Sprintf("7435692934957%06d", count-i)
			}
			for _, format := range []string{"json", "pretty"} {
				out, _ := captureDeleteDryRun(t, client.New(server.URL, "test"), ids, format)
				var result deleteResult
				if err := json.Unmarshal([]byte(out), &result); err != nil {
					t.Fatal(err)
				}
				if !result.DryRun || result.Count != count || len(result.Cards) != count || result.Tags != nil {
					t.Fatalf("wrong preview: count=%d cards=%d", result.Count, len(result.Cards))
				}
				for i, card := range result.Cards {
					if card.ID != ids[i] || card.Title != "" || card.URL != "" {
						t.Fatalf("wrong card %d: %+v", i, card)
					}
				}
			}
			out, log := captureDeleteDryRun(t, client.New(server.URL, "test"), ids, "text")
			if out != "" || !strings.Contains(log, fmt.Sprintf("Would delete %d card(s)", count)) || strings.Contains(log, ids[0]) {
				t.Fatalf("large text preview changed: %q %q", out, log)
			}
			if requests.Load() != 0 {
				t.Fatalf("preview made %d HTTP requests, including possible writes", requests.Load())
			}
		})
	}
}

func TestDeleteDryRunSmallJSONRetainsDetails(t *testing.T) {
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		if r.Method != http.MethodGet || r.URL.Path != "/c/api/cli/card/detail" {
			t.Errorf("unexpected request: %s %s", r.Method, r.URL.Path)
		}
		id := r.URL.Query().Get("id")
		_ = json.NewEncoder(w).Encode(map[string]any{"code": 200, "data": client.CardDetail{ID: id, Title: "Title " + id, URL: "https://example.com/" + id}})
	}))
	defer server.Close()
	ids := []string{"a", "b", "c"}
	out, _ := captureDeleteDryRun(t, client.New(server.URL, "test"), ids, "json")
	var result deleteResult
	if err := json.Unmarshal([]byte(out), &result); err != nil {
		t.Fatal(err)
	}
	if !result.DryRun || result.Count != 3 || len(result.Cards) != 3 || requests.Load() != 3 {
		t.Fatalf("small preview changed: %+v requests=%d", result, requests.Load())
	}
	for i, card := range result.Cards {
		if card.ID != ids[i] || card.Title != "Title "+ids[i] || card.URL != "https://example.com/"+ids[i] {
			t.Fatalf("missing detail: %+v", card)
		}
	}
}
