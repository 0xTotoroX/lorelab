package topic

import (
	"context"
	"fmt"
	"reflect"
	"sort"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/OLCUBO/cubox-cli/internal/client"
)

const PlanVersion = "cubox-topic-plan/v1"

// Plan keeps review decisions and card IDs, never full article text.
type Plan struct {
	Version    string      `json:"version"`
	Cards      []Result    `json:"cards"`
	Candidates []Candidate `json:"candidates"`
}

type Candidate struct {
	Name    string   `json:"name"`
	CardIDs []string `json:"card_ids"`
	Review  string   `json:"review"` // pending, approved, merged, rejected
	Target  string   `json:"target,omitempty"`
}

type BatchReport struct {
	Results []Result `json:"results"`
	Applied int      `json:"applied"`
}

// Collect previews each card and groups new concepts for a later review.
func Collect(ctx context.Context, store Store, classifier Classifier, ids []string) (Plan, error) {
	plan := Plan{Version: PlanVersion, Cards: []Result{}, Candidates: []Candidate{}}
	if len(ids) == 0 {
		return plan, fmt.Errorf("at least one card ID is required")
	}
	seen := make(map[string]bool, len(ids))
	byName := map[string][]string{}
	previewStore := &cachedReadStore{Store: store}
	for _, id := range ids {
		if err := ctx.Err(); err != nil {
			return Plan{}, err
		}
		id = strings.TrimSpace(id)
		if id == "" || seen[id] {
			return Plan{}, fmt.Errorf("card IDs must be nonempty and unique")
		}
		seen[id] = true
		result, err := Process(ctx, previewStore, classifier, id, false)
		if err != nil {
			return Plan{}, fmt.Errorf("collecting card %s: %w", id, err)
		}
		plan.Cards = append(plan.Cards, result)
		for _, name := range result.Suggested {
			byName[name] = append(byName[name], id)
		}
	}
	for name, cardIDs := range byName {
		sort.Strings(cardIDs)
		plan.Candidates = append(plan.Candidates, Candidate{Name: name, CardIDs: cardIDs, Review: "pending"})
	}
	sort.Slice(plan.Candidates, func(i, j int) bool {
		a, b := plan.Candidates[i], plan.Candidates[j]
		if len(a.CardIDs) != len(b.CardIDs) {
			return len(a.CardIDs) > len(b.CardIDs)
		}
		return a.Name < b.Name
	})
	return plan, nil
}

// SetReview records a decision without changing Cubox tags or cards.
func (p *Plan) SetReview(name, review, target string) error {
	if err := p.Validate(false); err != nil {
		return err
	}
	if review != "approved" && review != "merged" && review != "rejected" {
		return fmt.Errorf("review must be approved, merged, or rejected")
	}
	if review == "rejected" {
		if target != "" {
			return fmt.Errorf("rejected topics cannot have a target")
		}
	} else {
		if target == "" && review == "approved" {
			target = name
		}
		if !validTopicName(target) {
			return fmt.Errorf("target must be a valid topic leaf name")
		}
	}
	for i := range p.Candidates {
		if p.Candidates[i].Name == name {
			p.Candidates[i].Review = review
			p.Candidates[i].Target = target
			return nil
		}
	}
	return fmt.Errorf("candidate %q is not in the plan", name)
}

func validTopicName(name string) bool {
	if strings.IndexFunc(name, unicode.IsControl) >= 0 {
		return false
	}
	return name != "" && name == strings.TrimSpace(name) && !strings.Contains(name, "/") &&
		utf8.RuneCountInString(name) <= 40 && name != "主题" && name != "来源" &&
		name != "处理" && name != "skill" && name != "笔记"
}

// Validate detects accidental edits to the plan's card and candidate mapping.
func (p Plan) Validate(requireReviewed bool) error {
	if p.Version != PlanVersion || len(p.Cards) == 0 {
		return fmt.Errorf("invalid or empty topic plan")
	}
	seenCards := map[string]bool{}
	expected := map[string][]string{}
	for _, card := range p.Cards {
		if card.CardID == "" || seenCards[card.CardID] {
			return fmt.Errorf("plan contains duplicate or empty card IDs")
		}
		seenCards[card.CardID] = true
		if card.Status == "insufficient" && len(card.Suggested) > 0 {
			return fmt.Errorf("insufficient card %s has topic suggestions", card.CardID)
		}
		if len(card.Topics)+len(card.Suggested) > maxTopics {
			return fmt.Errorf("card %s has too many topic choices", card.CardID)
		}
		seenOnCard := map[string]bool{}
		for _, name := range card.Suggested {
			if !validTopicName(name) {
				return fmt.Errorf("invalid candidate name %q", name)
			}
			if seenOnCard[name] {
				return fmt.Errorf("card %s has duplicate candidate %q", card.CardID, name)
			}
			seenOnCard[name] = true
			expected[name] = append(expected[name], card.CardID)
		}
	}
	if len(expected) != len(p.Candidates) {
		return fmt.Errorf("candidate list does not match card suggestions")
	}
	seenCandidates := map[string]bool{}
	for _, candidate := range p.Candidates {
		if seenCandidates[candidate.Name] || !validTopicName(candidate.Name) {
			return fmt.Errorf("duplicate or invalid candidate %q", candidate.Name)
		}
		seenCandidates[candidate.Name] = true
		want, ok := expected[candidate.Name]
		sort.Strings(want)
		got := append([]string(nil), candidate.CardIDs...)
		sort.Strings(got)
		if !ok || !reflect.DeepEqual(want, got) {
			return fmt.Errorf("candidate %q has mismatched card IDs", candidate.Name)
		}
		if requireReviewed && candidate.Review == "pending" {
			return fmt.Errorf("candidate %q still needs review", candidate.Name)
		}
		switch candidate.Review {
		case "pending", "rejected":
			if candidate.Target != "" {
				return fmt.Errorf("candidate %q has an unexpected target", candidate.Name)
			}
		case "approved", "merged":
			if !validTopicName(candidate.Target) {
				return fmt.Errorf("candidate %q has an invalid target", candidate.Name)
			}
		default:
			return fmt.Errorf("candidate %q has an unknown review status", candidate.Name)
		}
	}
	return nil
}

// Backfill reclassifies the plan's cards against the current approved vocabulary.
// It never creates tags; approved candidate targets must already exist under 主题.
func Backfill(ctx context.Context, store Store, classifier Classifier, plan Plan, apply bool) (BatchReport, error) {
	return backfill(ctx, store, classifier, plan, apply, true)
}

func backfill(ctx context.Context, store Store, classifier Classifier, plan Plan, apply, requireReviewed bool) (BatchReport, error) {
	report := BatchReport{Results: []Result{}}
	if err := plan.Validate(requireReviewed); err != nil {
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
	aliases := map[string]string{}
	rejected := []string{}
	pending := map[string]bool{}
	for _, candidate := range plan.Candidates {
		if candidate.Review == "pending" {
			pending[candidate.Name] = true
		}
	}
	for _, candidate := range plan.Candidates {
		if (candidate.Review == "approved" || candidate.Review == "merged") && !available[candidate.Target] &&
			!(!requireReviewed && candidate.Review == "merged" && pending[candidate.Target]) {
			return report, fmt.Errorf("reviewed topic %q is missing under 主题; create it before backfill", candidate.Target)
		}
		if (candidate.Review == "approved" || candidate.Review == "merged") && candidate.Name != candidate.Target {
			aliases[candidate.Name] = candidate.Target
		}
		if candidate.Review == "rejected" {
			rejected = append(rejected, candidate.Name)
		}
	}
	backfillClassifier := &reviewedClassifier{Classifier: classifier, aliases: aliases, rejected: rejected}
	processStore := store
	if !apply {
		processStore = &cachedReadStore{Store: store, tags: tags, tagsLoaded: true}
	} else {
		processStore = &vocabularyGuardStore{Store: store, approved: approvedTopics(tags)}
	}
	for _, card := range plan.Cards {
		if err := ctx.Err(); err != nil {
			return report, fmt.Errorf("backfill stopped after %d verified applied cards: %w", report.Applied, err)
		}
		result, err := Process(ctx, processStore, backfillClassifier, card.CardID, apply)
		if err != nil {
			if apply {
				return report, fmt.Errorf("backfill stopped at card %s after %d verified applied cards; the current card may also have changed: %w", card.CardID, report.Applied, err)
			}
			return report, fmt.Errorf("backfill preview stopped at card %s: %w", card.CardID, err)
		}
		report.Results = append(report.Results, result)
		if result.Status == "applied" {
			report.Applied++
		}
	}
	return report, nil
}

type vocabularyGuardStore struct {
	Store
	approved []ApprovedTopic
}

func (s *vocabularyGuardStore) ListTags() ([]client.Tag, error) {
	tags, err := s.Store.ListTags()
	if err != nil {
		return nil, err
	}
	if !sameApprovedTopics(s.approved, approvedTopics(tags)) {
		return nil, fmt.Errorf("approved topic vocabulary changed during backfill")
	}
	return tags, nil
}

type reviewedClassifier struct {
	Classifier
	aliases  map[string]string
	rejected []string
}

func (c *reviewedClassifier) Classify(ctx context.Context, input Input) (Decision, error) {
	input.Aliases = c.aliases
	input.Rejected = c.rejected
	decision, err := c.Classifier.Classify(ctx, input)
	if err != nil {
		return decision, err
	}
	blocked := map[string]bool{}
	for name := range c.aliases {
		blocked[name] = true
	}
	for _, name := range c.rejected {
		blocked[name] = true
	}
	filtered := []string{}
	for _, name := range decision.Suggested {
		if !blocked[strings.TrimSpace(name)] {
			filtered = append(filtered, name)
		}
	}
	decision.Suggested = filtered
	return decision, nil
}

// cachedReadStore holds one vocabulary and folder snapshot during a preview batch.
type cachedReadStore struct {
	Store
	tags          []client.Tag
	tagsErr       error
	tagsLoaded    bool
	folders       []client.Folder
	foldersErr    error
	foldersLoaded bool
}

func (s *cachedReadStore) ListTags() ([]client.Tag, error) {
	if !s.tagsLoaded {
		s.tags, s.tagsErr = s.Store.ListTags()
		s.tagsLoaded = true
	}
	return s.tags, s.tagsErr
}

func (s *cachedReadStore) ListFolders() ([]client.Folder, error) {
	if !s.foldersLoaded {
		s.folders, s.foldersErr = s.Store.ListFolders()
		s.foldersLoaded = true
	}
	return s.folders, s.foldersErr
}
