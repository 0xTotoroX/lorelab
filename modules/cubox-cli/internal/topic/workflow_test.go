package topic

import (
	"context"
	"fmt"
	"strings"
	"testing"

	"github.com/OLCUBO/cubox-cli/internal/client"
)

type workflowStore struct {
	tags      []client.Tag
	cards     map[string]client.CardDetail
	addCalls  int
	failAddID string
}

func (s *workflowStore) ListTags() ([]client.Tag, error)       { return s.tags, nil }
func (s *workflowStore) ListFolders() ([]client.Folder, error) { return nil, nil }
func (s *workflowStore) GetCardDetail(id string) (*client.CardDetail, error) {
	card, ok := s.cards[id]
	if !ok {
		return nil, nil
	}
	card.Tags = append([]string(nil), card.Tags...)
	return &card, nil
}
func (s *workflowStore) AddCardTags(req *client.CardAddTagsRequest) error {
	if req.ID == s.failAddID {
		return fmt.Errorf("simulated write failure")
	}
	s.addCalls++
	card := s.cards[req.ID]
	card.Tags = append(card.Tags, req.AddTagNestedNames...)
	s.cards[req.ID] = card
	return nil
}

func TestBackfillReportsPartialSimulation(t *testing.T) {
	store, model := workflowFixture()
	plan, err := Collect(context.Background(), store, model, []string{"a", "b"})
	if err != nil {
		t.Fatal(err)
	}
	for _, decision := range []struct{ name, review, target string }{
		{"MCP", "approved", ""},
		{"MCP工具", "merged", "MCP"},
		{"AI", "rejected", ""},
	} {
		if err := plan.SetReview(decision.name, decision.review, decision.target); err != nil {
			t.Fatal(err)
		}
	}
	store.tags = []client.Tag{
		{ID: "root", Name: "主题", NestedName: "主题"},
		{ID: "mcp", Name: "MCP", NestedName: "主题/MCP", ParentID: parent("root")},
	}
	model.decisions["protocol"] = Decision{Sufficient: true, TopicIDs: []string{"mcp"}}
	model.decisions["knowledge"] = Decision{Sufficient: true, TopicIDs: []string{"mcp"}}
	store.failAddID = "b"
	report, err := Backfill(context.Background(), store, model, plan, true)
	if err == nil || report.Applied != 1 || len(report.Results) != 1 ||
		len(missing([]string{"主题/MCP"}, store.cards["a"].Tags)) != 0 ||
		len(missing([]string{"主题/MCP"}, store.cards["b"].Tags)) == 0 {
		t.Fatalf("partial result was hidden: report=%+v err=%v", report, err)
	}
}

type workflowClassifier struct {
	decisions map[string]Decision
	calls     int
	inputs    []Input
}

func (c *workflowClassifier) Classify(_ context.Context, input Input) (Decision, error) {
	c.calls++
	c.inputs = append(c.inputs, input)
	if strings.Contains(input.Content, "知识库") {
		return c.decisions["knowledge"], nil
	}
	return c.decisions["protocol"], nil
}

func workflowFixture() (*workflowStore, *workflowClassifier) {
	s := &workflowStore{cards: map[string]client.CardDetail{
		"a": {ID: "a", Title: "MCP 协议", Content: strings.Repeat("正文讲解 MCP 的协议与工具调用。", 10), Tags: []string{"来源/GitHub", "处理/00 待审"}, Folder: &client.Folder{ID: "f1", Name: "AI"}},
		"b": {ID: "b", Title: "MCP 知识库", Content: strings.Repeat("正文讨论用 MCP 连接知识库。", 12), Tags: []string{"笔记"}, Folder: &client.Folder{ID: "f2", Name: "知识管理"}},
		"c": {ID: "c", Title: "仅标题", Content: "短内容", Description: "很短", Tags: []string{"来源/X"}},
	}}
	c := &workflowClassifier{decisions: map[string]Decision{
		"protocol":  {Sufficient: true, Suggested: []string{"MCP", "AI"}, Reason: "正文主要讲 MCP"},
		"knowledge": {Sufficient: true, Suggested: []string{"MCP", "MCP工具"}, Reason: "正文主要讲 MCP 与知识库"},
	}}
	return s, c
}

func TestCollectReviewBackfillSimulation(t *testing.T) {
	store, model := workflowFixture()
	plan, err := Collect(context.Background(), store, model, []string{"a", "b", "c"})
	if err != nil || len(plan.Cards) != 3 || len(plan.Candidates) != 3 || model.calls != 2 || store.addCalls != 0 {
		t.Fatalf("unexpected collection: plan=%+v calls=%d err=%v", plan, model.calls, err)
	}
	if plan.Candidates[0].Name != "MCP" || len(plan.Candidates[0].CardIDs) != 2 || plan.Cards[2].Status != "insufficient" {
		t.Fatalf("candidate grouping or insufficient card failed: %+v", plan)
	}
	if _, err := Backfill(context.Background(), store, model, plan, false); err == nil {
		t.Fatal("pending plan was accepted")
	}
	if err := plan.SetReview("MCP", "approved", ""); err != nil {
		t.Fatal(err)
	}
	if err := plan.SetReview("MCP工具", "merged", "MCP"); err != nil {
		t.Fatal(err)
	}
	if err := plan.SetReview("AI", "rejected", ""); err != nil {
		t.Fatal(err)
	}
	if _, err := Backfill(context.Background(), store, model, plan, false); err == nil {
		t.Fatal("approved topic missing from Cubox was accepted")
	}
	store.tags = []client.Tag{
		{ID: "root", Name: "主题", NestedName: "主题"},
		{ID: "mcp", Name: "MCP", NestedName: "主题/MCP", ParentID: parent("root")},
	}
	model.decisions["protocol"] = Decision{Sufficient: true, TopicIDs: []string{"mcp"}, Suggested: []string{"AI"}}
	model.decisions["knowledge"] = Decision{Sufficient: true, TopicIDs: []string{"mcp"}, Suggested: []string{"MCP工具"}}
	preview, err := Backfill(context.Background(), store, model, plan, false)
	if err != nil || preview.Applied != 0 || store.addCalls != 0 || len(preview.Results) != 3 || preview.Results[2].Status != "insufficient" ||
		len(preview.Results[0].Suggested) != 0 || len(preview.Results[1].Suggested) != 0 {
		t.Fatalf("backfill preview changed cards: report=%+v err=%v", preview, err)
	}
	if model.inputs[len(model.inputs)-1].Aliases["MCP工具"] != "MCP" || len(model.inputs[len(model.inputs)-1].Rejected) != 1 {
		t.Fatal("reviewed aliases and rejections did not reach the classifier")
	}
	applied, err := Backfill(context.Background(), store, model, plan, true)
	if err != nil || applied.Applied != 2 || store.addCalls != 2 || applied.Results[2].Status != "insufficient" {
		t.Fatalf("backfill apply failed: report=%+v err=%v", applied, err)
	}
	for _, id := range []string{"a", "b"} {
		if len(missing([]string{"主题/MCP"}, store.cards[id].Tags)) != 0 {
			t.Fatalf("card %s missed reviewed topic", id)
		}
	}
	if len(missing([]string{"来源/GitHub", "处理/00 待审"}, store.cards["a"].Tags)) != 0 ||
		store.cards["a"].Folder.ID != "f1" || len(store.cards["c"].Tags) != 1 {
		t.Fatal("backfill changed existing tags, folder, or insufficient card")
	}
}

func TestCollectRejectsDuplicateIDsAndPlanTampering(t *testing.T) {
	store, model := workflowFixture()
	if _, err := Collect(context.Background(), store, model, []string{"a", "a"}); err == nil {
		t.Fatal("duplicate card ID was accepted")
	}
	plan, err := Collect(context.Background(), store, model, []string{"a"})
	if err != nil {
		t.Fatal(err)
	}
	plan.Candidates[0].CardIDs = []string{"b"}
	if err := plan.Validate(false); err == nil {
		t.Fatal("changed candidate-card mapping was accepted")
	}
}
