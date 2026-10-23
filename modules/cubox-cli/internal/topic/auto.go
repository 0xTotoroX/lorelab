package topic

import (
	"context"
	"fmt"
	"sort"
	"strings"

	"github.com/OLCUBO/cubox-cli/internal/client"
)

// Occurrence contains the current evidence for one proposed topic on one card.
type Occurrence struct {
	CardID   string `json:"card_id"`
	Title    string `json:"title"`
	Evidence string `json:"evidence"`
	Excerpt  string `json:"excerpt"`
	Reason   string `json:"reason"`
}

type CandidateEvidence struct {
	Name        string       `json:"name"`
	Occurrences []Occurrence `json:"occurrences"`
}

type ConsolidationInput struct {
	Approved   []string            `json:"approved_topics"`
	Candidates []CandidateEvidence `json:"candidates"`
}

type Assignment struct {
	Name             string   `json:"name"`
	Target           string   `json:"target"`
	SupportedCardIDs []string `json:"supported_card_ids"`
}

type Consolidation struct {
	Assignments []Assignment `json:"assignments"`
}

type Consolidator interface {
	Consolidate(context.Context, ConsolidationInput) (Consolidation, error)
}

type AutoReviewReport struct {
	Approved []string `json:"approved"`
	Merged   []string `json:"merged"`
	Pending  []string `json:"pending"`
}

// AutoReview only changes the local plan. The model may merge exact synonyms,
// but a new canonical name needs support from two distinct, substantive bodies.
func AutoReview(ctx context.Context, store Store, model Consolidator, plan *Plan) (AutoReviewReport, error) {
	report := AutoReviewReport{Approved: []string{}, Merged: []string{}, Pending: []string{}}
	if err := plan.Validate(false); err != nil {
		return report, err
	}
	tags, err := store.ListTags()
	if err != nil {
		return report, err
	}
	approved := map[string]bool{}
	input := ConsolidationInput{Approved: []string{}, Candidates: []CandidateEvidence{}}
	for _, tag := range approvedTopics(tags) {
		name := strings.TrimPrefix(tag.Name, "主题/")
		approved[name] = true
		input.Approved = append(input.Approved, name)
	}
	byName := map[string]Candidate{}
	manuallyApproved := map[string]bool{}
	for _, candidate := range plan.Candidates {
		if candidate.Review == "pending" {
			byName[candidate.Name] = candidate
		} else if candidate.Review == "approved" {
			manuallyApproved[candidate.Target] = true
		}
	}
	for name := range manuallyApproved {
		if !approved[name] {
			input.Approved = append(input.Approved, name)
		}
	}
	sort.Strings(input.Approved)
	if len(byName) == 0 {
		return report, nil
	}
	cards := map[string]Result{}
	for _, card := range plan.Cards {
		cards[card.CardID] = card
	}
	for _, candidate := range plan.Candidates {
		if candidate.Review != "pending" {
			continue
		}
		evidence := CandidateEvidence{Name: candidate.Name, Occurrences: []Occurrence{}}
		for _, id := range candidate.CardIDs {
			if err := ctx.Err(); err != nil {
				return report, err
			}
			card, err := store.GetCardDetail(id)
			if err != nil {
				return report, err
			}
			if card == nil || card.ID != id {
				return report, fmt.Errorf("card detail did not match requested ID %s", id)
			}
			content, kind, _ := evidenceText(card)
			if card.Title != cards[id].Title || kind != cards[id].Evidence {
				return report, fmt.Errorf("card %s changed since collection; collect a new plan", id)
			}
			if kind == "description" {
				content = truncateRunes(card.Description, 4000)
			}
			evidence.Occurrences = append(evidence.Occurrences, Occurrence{
				CardID: id, Title: card.Title, Evidence: kind,
				Excerpt: truncateRunes(content, 4000), Reason: cards[id].Reason,
			})
		}
		input.Candidates = append(input.Candidates, evidence)
	}
	consolidated, err := model.Consolidate(ctx, input)
	if err != nil {
		return report, err
	}
	assignments := map[string]Assignment{}
	for _, assignment := range consolidated.Assignments {
		candidate, ok := byName[assignment.Name]
		if !ok || assignments[assignment.Name].Name != "" || !validTopicName(assignment.Target) ||
			(!approved[assignment.Target] && !manuallyApproved[assignment.Target] && byName[assignment.Target].Name == "") {
			return report, fmt.Errorf("invalid synonym assignment for %q", assignment.Name)
		}
		allowed := map[string]bool{}
		for _, id := range candidate.CardIDs {
			allowed[id] = true
		}
		seen := map[string]bool{}
		for _, id := range assignment.SupportedCardIDs {
			if !allowed[id] || seen[id] {
				return report, fmt.Errorf("invalid supporting card %q for %q", id, assignment.Name)
			}
			seen[id] = true
		}
		assignments[assignment.Name] = assignment
	}
	if len(assignments) != len(byName) {
		return report, fmt.Errorf("model did not assess every pending topic candidate")
	}
	for _, assignment := range assignments {
		if !approved[assignment.Target] && !manuallyApproved[assignment.Target] && assignments[assignment.Target].Target != assignment.Target {
			return report, fmt.Errorf("synonym target %q must be canonical", assignment.Target)
		}
	}
	supported := map[string]map[string]bool{}
	for _, assignment := range assignments {
		if supported[assignment.Target] == nil {
			supported[assignment.Target] = map[string]bool{}
		}
		for _, id := range assignment.SupportedCardIDs {
			card := cards[id]
			if card.Evidence == "content" && strings.TrimSpace(card.Reason) != "" {
				supported[assignment.Target][id] = true
			}
		}
	}
	// Apply only after all model outputs have passed validation.
	for i := range plan.Candidates {
		candidate := &plan.Candidates[i]
		if candidate.Review != "pending" {
			continue
		}
		target := assignments[candidate.Name].Target
		switch {
		case candidate.Name != target:
			candidate.Review, candidate.Target = "merged", target
			report.Merged = append(report.Merged, candidate.Name+" → "+target)
		case candidate.Name == target && !approved[target] && len(supported[target]) >= 2:
			candidate.Review, candidate.Target = "approved", target
			report.Approved = append(report.Approved, target)
		default:
			report.Pending = append(report.Pending, candidate.Name)
		}
	}
	sort.Strings(report.Approved)
	sort.Strings(report.Merged)
	sort.Strings(report.Pending)
	return report, plan.Validate(false)
}

type TagCreator interface {
	CreateTopicTag(name, parentID string) error
}

type AutoBackfillReport struct {
	BatchReport
	Created     []string `json:"created"`
	WouldCreate []string `json:"would_create"`
	Pending     []string `json:"pending"`
}

// AutoBackfill previews by default. Apply creates approved tags, then uses the
// ordinary verified card backfill. Pending names are retained in the plan.
func AutoBackfill(ctx context.Context, store Store, creator TagCreator, classifier Classifier, plan Plan, apply bool) (AutoBackfillReport, error) {
	report := AutoBackfillReport{BatchReport: BatchReport{Results: []Result{}}, Created: []string{}, WouldCreate: []string{}, Pending: []string{}}
	if err := plan.Validate(false); err != nil {
		return report, err
	}
	tags, err := store.ListTags()
	if err != nil {
		return report, err
	}
	available := map[string]bool{}
	for _, tag := range approvedTopics(tags) {
		available[strings.TrimPrefix(tag.Name, "主题/")] = true
	}
	needed := map[string]bool{}
	for _, candidate := range plan.Candidates {
		if candidate.Review == "pending" {
			report.Pending = append(report.Pending, candidate.Name)
		}
		if candidate.Review == "approved" && !available[candidate.Target] {
			needed[candidate.Target] = true
		}
	}
	for name := range needed {
		report.WouldCreate = append(report.WouldCreate, name)
	}
	sort.Strings(report.WouldCreate)
	if !apply {
		previewTags := append([]client.Tag(nil), tags...)
		rootID := ""
		for _, tag := range previewTags {
			if tag.Name == "主题" && tag.ParentID == nil {
				rootID = tag.ID
				break
			}
		}
		if rootID == "" && len(report.WouldCreate) > 0 {
			rootID = "preview-topic-root"
			previewTags = append(previewTags, client.Tag{ID: rootID, Name: "主题", NestedName: "主题"})
		}
		for i, name := range report.WouldCreate {
			previewTags = append(previewTags, client.Tag{
				ID: fmt.Sprintf("preview-topic-%d", i), Name: name,
				NestedName: "主题/" + name, ParentID: &rootID,
			})
		}
		batch, err := backfill(ctx, &staticTagsStore{Store: store, tags: previewTags}, classifier, plan, false, false)
		report.BatchReport = batch
		return report, err
	}
	if len(report.WouldCreate) > 0 && creator == nil {
		return report, fmt.Errorf("tag creator is required to apply newly approved topics")
	}
	rootID := ""
	for _, tag := range tags {
		if tag.Name == "主题" && tag.ParentID == nil {
			rootID = tag.ID
			break
		}
	}
	if len(report.WouldCreate) > 0 && rootID == "" {
		if err := creator.CreateTopicTag("主题", ""); err != nil {
			return report, fmt.Errorf("creating 主题 root: %w", err)
		}
		tags, err = store.ListTags()
		if err != nil {
			return report, err
		}
		for _, tag := range tags {
			if tag.Name == "主题" && tag.ParentID == nil {
				rootID = tag.ID
				break
			}
		}
		if rootID == "" {
			return report, fmt.Errorf("created 主题 root but could not verify it")
		}
		report.Created = append(report.Created, "主题")
	}
	for _, name := range report.WouldCreate {
		if err := ctx.Err(); err != nil {
			return report, err
		}
		if err := creator.CreateTopicTag(name, rootID); err != nil {
			return report, fmt.Errorf("created %v; creating 主题/%s: %w", report.Created, name, err)
		}
		tags, err = store.ListTags()
		if err != nil {
			return report, err
		}
		found := false
		for _, tag := range approvedTopics(tags) {
			if tag.Name == "主题/"+name {
				found = true
				break
			}
		}
		if !found {
			return report, fmt.Errorf("created 主题/%s but could not verify it", name)
		}
		report.Created = append(report.Created, "主题/"+name)
	}
	if len(approvedTopics(tags)) == 0 {
		batch, err := backfill(ctx, store, classifier, plan, false, false)
		report.BatchReport = batch
		return report, err
	}
	batch, err := backfill(ctx, store, classifier, plan, true, false)
	report.BatchReport = batch
	return report, err
}

type staticTagsStore struct {
	Store
	tags []client.Tag
}

func (s *staticTagsStore) ListTags() ([]client.Tag, error) { return s.tags, nil }

// WebTagCreator bridges the existing Cubox web/app tag-new endpoint.
type WebTagCreator struct{ Web *client.Client }

func (c WebTagCreator) CreateTopicTag(name, parentID string) error {
	_, err := c.Web.WebTagNew(name, parentID)
	return err
}
