package cmd

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/OLCUBO/cubox-cli/internal/topic"
)

func TestLocalTopicPlanReviewRoundTrip(t *testing.T) {
	path := filepath.Join(t.TempDir(), "topic-plan.json")
	plan := topic.Plan{
		Version:    topic.PlanVersion,
		Cards:      []topic.Result{{CardID: "card-1", Title: "MCP 文章", Status: "preview", Suggested: []string{"MCP"}}},
		Candidates: []topic.Candidate{{Name: "MCP", CardIDs: []string{"card-1"}, Review: "pending"}},
	}
	if err := saveTopicPlan(path, plan, true); err != nil {
		t.Fatal(err)
	}
	if err := saveTopicPlan(path, plan, true); err == nil {
		t.Fatal("collect overwrote an existing review plan")
	}
	info, err := os.Stat(path)
	if err != nil || info.Mode().Perm() != 0600 {
		t.Fatalf("review plan should be private: info=%v err=%v", info, err)
	}
	loaded, err := loadTopicPlan(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := loaded.SetReview("MCP", "approved", ""); err != nil {
		t.Fatal(err)
	}
	if err := saveTopicPlan(path, loaded, false); err != nil {
		t.Fatal(err)
	}
	reloaded, err := loadTopicPlan(path)
	if err != nil || reloaded.Candidates[0].Review != "approved" || reloaded.Candidates[0].Target != "MCP" {
		t.Fatalf("review was not persisted: %+v err=%v", reloaded, err)
	}
}
