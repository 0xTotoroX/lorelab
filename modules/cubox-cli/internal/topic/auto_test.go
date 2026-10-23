package topic

import (
	"context"
	"fmt"
	"strings"
	"testing"

	"github.com/OLCUBO/cubox-cli/internal/client"
)

type autoStore struct {
	workflowStore
	created []string
}

func (s *autoStore) CreateTopicTag(name, parentID string) error {
	for _, tag := range s.tags {
		if tag.Name == name && ((parentID == "" && tag.ParentID == nil) ||
			(tag.ParentID != nil && *tag.ParentID == parentID)) {
			return fmt.Errorf("duplicate tag")
		}
	}
	id := fmt.Sprintf("created-%d", len(s.created)+1)
	tag := client.Tag{ID: id, Name: name, NestedName: name}
	if parentID != "" {
		tag.ParentID = parent(parentID)
		tag.NestedName = "主题/" + name
	}
	s.tags = append(s.tags, tag)
	s.created = append(s.created, tag.NestedName)
	return nil
}

type autoModel struct{ bad bool }

func (m autoModel) Classify(_ context.Context, input Input) (Decision, error) {
	byName := map[string]string{}
	for _, tag := range input.Approved {
		byName[strings.TrimPrefix(tag.Name, "主题/")] = tag.ID
	}
	switch input.Title {
	case "RAG 入门":
		if id := byName["RAG"]; id != "" {
			return Decision{Sufficient: true, TopicIDs: []string{id}, Reason: "正文主要讲 RAG 检索"}, nil
		}
		return Decision{Sufficient: true, Suggested: []string{"RAG"}, Reason: "正文主要讲 RAG 检索"}, nil
	case "检索增强生成实践":
		if id := byName["RAG"]; id != "" {
			return Decision{Sufficient: true, TopicIDs: []string{id}, Reason: "正文主要讲检索增强生成"}, nil
		}
		return Decision{Sufficient: true, Suggested: []string{"检索增强生成"}, Reason: "正文主要讲检索增强生成"}, nil
	case "MCP 工具":
		if id := byName["MCP"]; id != "" && len(input.Aliases) > 0 {
			return Decision{Sufficient: true, TopicIDs: []string{id}, Reason: "正文讲 MCP"}, nil
		}
		return Decision{Sufficient: true, Suggested: []string{"MCP工具"}, Reason: "正文讲 MCP 工具"}, nil
	case "MCP 官方教程":
		return Decision{Sufficient: true, TopicIDs: []string{byName["MCP"]}, Reason: "正文核心是 MCP"}, nil
	case "图像生成":
		return Decision{Sufficient: true, Suggested: []string{"图像生成"}, Reason: "正文讲图像生成"}, nil
	case "跨设备同步":
		return Decision{Sufficient: true, Suggested: []string{"跨设备同步"}, Reason: "描述介绍跨设备同步"}, nil
	}
	return Decision{}, fmt.Errorf("unexpected title %q", input.Title)
}

func (m autoModel) Consolidate(_ context.Context, _ ConsolidationInput) (Consolidation, error) {
	if m.bad {
		return Consolidation{Assignments: []Assignment{{Name: "RAG", Target: "RAG", SupportedCardIDs: []string{"not-in-plan"}}}}, nil
	}
	return Consolidation{Assignments: []Assignment{
		{Name: "RAG", Target: "RAG", SupportedCardIDs: []string{"a"}},
		{Name: "检索增强生成", Target: "RAG", SupportedCardIDs: []string{"b"}},
		{Name: "MCP工具", Target: "MCP", SupportedCardIDs: []string{"e"}},
		{Name: "图像生成", Target: "图像生成", SupportedCardIDs: []string{"c"}},
		{Name: "跨设备同步", Target: "跨设备同步", SupportedCardIDs: []string{"d"}},
	}}, nil
}

func autoFixture() *autoStore {
	article := func(s string) string { return strings.Repeat(s, 12) }
	return &autoStore{workflowStore: workflowStore{
		tags: []client.Tag{
			{ID: "root", Name: "主题", NestedName: "主题"},
			{ID: "mcp", Name: "MCP", NestedName: "主题/MCP", ParentID: parent("root")},
		},
		cards: map[string]client.CardDetail{
			"a": {ID: "a", Title: "RAG 入门", Content: article("正文讲解 RAG 检索和生成。"), Tags: []string{"来源/GitHub", "处理/00 待审"}, Folder: &client.Folder{ID: "f1"}},
			"b": {ID: "b", Title: "检索增强生成实践", Content: article("正文分析检索增强生成流程。"), Tags: []string{"笔记"}, Folder: &client.Folder{ID: "f2"}},
			"c": {ID: "c", Title: "图像生成", Content: article("正文聚焦图像生成过程。"), Tags: []string{"来源/X"}},
			"d": {ID: "d", Title: "跨设备同步", Description: article("描述介绍设备同步功能。"), Tags: []string{"来源/网页"}},
			"e": {ID: "e", Title: "MCP 工具", Content: article("正文解释 MCP 工具调用。"), Tags: []string{"skill"}},
			"f": {ID: "f", Title: "短卡", Content: "太短", Tags: []string{"来源/X"}},
			"g": {ID: "g", Title: "MCP 官方教程", Content: article("正文详细介绍 MCP 协议。"), Tags: []string{"来源/官网"}},
		},
	}}
}

func TestAutoWorkflowSimulation(t *testing.T) {
	store, model := autoFixture(), autoModel{}
	plan, err := Collect(context.Background(), store, model, []string{"a", "b", "c", "d", "e", "f", "g"})
	if err != nil || store.addCalls != 0 || len(plan.Candidates) != 5 {
		t.Fatalf("collect failed: plan=%+v err=%v", plan, err)
	}
	review, err := AutoReview(context.Background(), store, model, &plan)
	if err != nil || len(review.Approved) != 1 || review.Approved[0] != "RAG" ||
		len(review.Merged) != 2 || len(review.Pending) != 2 || len(store.created) != 0 {
		t.Fatalf("auto review failed: report=%+v err=%v", review, err)
	}
	preview, err := AutoBackfill(context.Background(), store, nil, model, plan, false)
	if err != nil || preview.Applied != 0 || len(preview.WouldCreate) != 1 ||
		preview.WouldCreate[0] != "RAG" || len(preview.Pending) != 2 || len(preview.Results) != 7 ||
		store.addCalls != 0 || len(store.created) != 0 {
		t.Fatalf("preview wrote data or omitted results: report=%+v err=%v", preview, err)
	}
	applied, err := AutoBackfill(context.Background(), store, store, model, plan, true)
	if err != nil || applied.Applied != 4 || len(applied.Created) != 1 || applied.Created[0] != "主题/RAG" ||
		store.addCalls != 4 || len(store.created) != 1 {
		t.Fatalf("auto apply failed: report=%+v err=%v", applied, err)
	}
	for _, tc := range []struct{ id, tag string }{{"a", "主题/RAG"}, {"b", "主题/RAG"}, {"e", "主题/MCP"}, {"g", "主题/MCP"}} {
		if len(missing([]string{tc.tag}, store.cards[tc.id].Tags)) != 0 {
			t.Fatalf("card %s lacks %s", tc.id, tc.tag)
		}
	}
	if len(store.cards["c"].Tags) != 1 || len(store.cards["d"].Tags) != 1 || len(store.cards["f"].Tags) != 1 ||
		store.cards["a"].Folder.ID != "f1" || len(missing([]string{"来源/GitHub", "处理/00 待审"}, store.cards["a"].Tags)) != 0 {
		t.Fatal("pending/insufficient card or original folder/tags changed")
	}
	t.Logf("approved=%v merged=%v pending=%v created=%v applied=%d; a=%v b=%v e=%v g=%v",
		review.Approved, review.Merged, review.Pending, applied.Created, applied.Applied,
		store.cards["a"].Tags, store.cards["b"].Tags, store.cards["e"].Tags, store.cards["g"].Tags)
}

func TestAutoReviewRejectsInvalidModelOutputWithoutChangingPlan(t *testing.T) {
	store := autoFixture()
	plan, err := Collect(context.Background(), store, autoModel{}, []string{"a", "b"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := AutoReview(context.Background(), store, autoModel{bad: true}, &plan); err == nil {
		t.Fatal("invalid supporting card was accepted")
	}
	for _, candidate := range plan.Candidates {
		if candidate.Review != "pending" {
			t.Fatal("invalid consolidation partly changed the plan")
		}
	}
}

func TestAutoBackfillCreatesMissingRootInSimulation(t *testing.T) {
	store := autoFixture()
	store.tags = nil
	model := autoModel{}
	plan, err := Collect(context.Background(), store, model, []string{"a", "b"})
	if err != nil {
		t.Fatal(err)
	}
	if err := plan.SetReview("RAG", "approved", ""); err != nil {
		t.Fatal(err)
	}
	if err := plan.SetReview("检索增强生成", "merged", "RAG"); err != nil {
		t.Fatal(err)
	}
	report, err := AutoBackfill(context.Background(), store, store, model, plan, true)
	if err != nil || report.Applied != 2 || len(report.Created) != 2 || report.Created[0] != "主题" || report.Created[1] != "主题/RAG" {
		t.Fatalf("missing root was not created and verified: report=%+v err=%v", report, err)
	}
}

func TestAutoBackfillLeavesAllPendingWithoutCreatingTags(t *testing.T) {
	store := autoFixture()
	store.tags = nil
	model := autoModel{}
	plan, err := Collect(context.Background(), store, model, []string{"c", "d", "f"})
	if err != nil {
		t.Fatal(err)
	}
	report, err := AutoBackfill(context.Background(), store, store, model, plan, true)
	if err != nil || len(report.Created) != 0 || report.Applied != 0 || len(report.Results) != 3 ||
		len(store.created) != 0 || store.addCalls != 0 {
		t.Fatalf("pending candidates caused writes: report=%+v err=%v", report, err)
	}
}

type singletonSynonymModel struct{}

func (singletonSynonymModel) Classify(_ context.Context, input Input) (Decision, error) {
	if input.Aliases["设备端智能"] == "端侧 AI" {
		return Decision{Sufficient: true, Suggested: []string{"端侧 AI"}, Reason: "正文主要讲端侧 AI"}, nil
	}
	return Decision{Sufficient: true, Suggested: []string{"端侧 AI", "设备端智能"}, Reason: "正文主要讲端侧 AI"}, nil
}

func (singletonSynonymModel) Consolidate(_ context.Context, _ ConsolidationInput) (Consolidation, error) {
	return Consolidation{Assignments: []Assignment{
		{Name: "端侧 AI", Target: "端侧 AI", SupportedCardIDs: []string{"one"}},
		{Name: "设备端智能", Target: "端侧 AI", SupportedCardIDs: []string{"one"}},
	}}, nil
}

func TestAutoReviewMergesSingletonSynonymsWithoutApproving(t *testing.T) {
	store := &autoStore{workflowStore: workflowStore{cards: map[string]client.CardDetail{
		"one": {ID: "one", Title: "单篇近义词", Content: strings.Repeat("正文主要讨论设备上的端侧 AI。", 12)},
	}}}
	model := singletonSynonymModel{}
	plan, err := Collect(context.Background(), store, model, []string{"one"})
	if err != nil {
		t.Fatal(err)
	}
	review, err := AutoReview(context.Background(), store, model, &plan)
	if err != nil || len(review.Approved) != 0 || len(review.Merged) != 1 || len(review.Pending) != 1 {
		t.Fatalf("singleton synonyms were not kept pending: %+v %v", review, err)
	}
	report, err := AutoBackfill(context.Background(), store, store, model, plan, true)
	if err != nil || len(report.Pending) != 1 || len(report.Created) != 0 || report.Applied != 0 ||
		len(store.created) != 0 || store.addCalls != 0 {
		t.Fatalf("singleton synonym created a tag: %+v %v", report, err)
	}
}
