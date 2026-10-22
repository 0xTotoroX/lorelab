package client

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

type batchTransport func(*http.Request) (*http.Response, error)

func (f batchTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func batchResponse(status int, body string) (*http.Response, error) {
	return &http.Response{StatusCode: status, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(body))}, nil
}

func cardResponse(id string) (*http.Response, error) {
	body, _ := json.Marshal(APIResponse{Code: 200, Data: json.RawMessage(fmt.Sprintf(`{"id":%q,"content":"Saved body.","annotations":[]}`, id))})
	return batchResponse(200, string(body))
}

func batchClient(transport batchTransport) *Client {
	c := New("https://cubox.example", "synthetic-test-token")
	c.httpClient.Transport = transport
	return c
}

func TestCardBatchConcurrencyAndSharedThrottle(t *testing.T) {
	for workers := 1; workers <= 4; workers++ {
		t.Run(fmt.Sprintf("workers_%d", workers), func(t *testing.T) {
			t.Parallel()
			var active, peak atomic.Int32
			var mu sync.Mutex
			var starts []time.Time
			started := make(chan struct{}, 16)
			release := make(chan struct{})
			var releaseOnce sync.Once
			defer releaseOnce.Do(func() { close(release) })
			c := batchClient(func(r *http.Request) (*http.Response, error) {
				if r.Method != http.MethodGet || r.URL.Path != "/c/api/cli/card/detail" || r.Header.Get("Authorization") != "Bearer synthetic-test-token" {
					t.Errorf("unexpected request method, path, or authorization")
				}
				n := active.Add(1)
				defer active.Add(-1)
				for old := peak.Load(); n > old; old = peak.Load() {
					if peak.CompareAndSwap(old, n) {
						break
					}
				}
				mu.Lock()
				starts = append(starts, time.Now())
				mu.Unlock()
				started <- struct{}{}
				<-release
				return cardResponse(r.URL.Query().Get("id"))
			})
			ids := []string{"a", "b", "c", "d", "e", "f"}
			ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
			defer cancel()
			var batch *CardBatch
			var err error
			done := make(chan struct{})
			go func() { defer close(done); batch, err = c.GetCardBatch(ctx, ids, workers) }()
			for i := 0; i < workers; i++ {
				select {
				case <-started:
				case <-ctx.Done():
					t.Fatal("workers did not start")
				}
			}
			select {
			case <-started:
				t.Fatal("more in-flight requests than configured workers")
			case <-time.After(minRequestInterval + 50*time.Millisecond):
			}
			releaseOnce.Do(func() { close(release) })
			<-done
			if err != nil || batch.Counts.OK != len(ids) || peak.Load() != int32(workers) {
				t.Fatalf("counts=%+v peak=%d err=%v", batch.Counts, peak.Load(), err)
			}
			for i := 1; i < len(starts); i++ {
				if gap := starts[i].Sub(starts[i-1]); gap < minRequestInterval-5*time.Millisecond {
					t.Fatalf("requests bypassed shared throttle: gap=%v", gap)
				}
			}
		})
	}
}

func TestCardBatchOrderDedupAndPartialFailure(t *testing.T) {
	t.Parallel()
	late := make(chan struct{})
	var mu sync.Mutex
	seen := map[string]int{}
	c := batchClient(func(r *http.Request) (*http.Response, error) {
		id := r.URL.Query().Get("id")
		mu.Lock()
		seen[id]++
		mu.Unlock()
		switch id {
		case "a":
			<-late
			return cardResponse(id)
		case "b":
			return batchResponse(403, "secret response must not be echoed")
		default:
			close(late)
			return cardResponse(id)
		}
	})
	batch, err := c.GetCardBatch(context.Background(), []string{" a ", "b", "a", "", "c", "b"}, 3)
	if !errors.Is(err, ErrCardBatchIncomplete) || batch.Counts != (CardBatchCounts{Total: 3, OK: 2, Error: 1}) {
		t.Fatalf("counts=%+v err=%v", batch.Counts, err)
	}
	for i, id := range []string{"a", "b", "c"} {
		if batch.Items[i].ID != id || seen[id] != 1 {
			t.Fatalf("lost order or duplicate request: items=%+v seen=%v", batch.Items, seen)
		}
	}
	if batch.Items[1].Error.HTTPStatus != 403 || batch.Items[1].Card != nil || batch.Items[1].ContentStatus != nil {
		t.Fatalf("unexpected failed item: %+v", batch.Items[1])
	}
	if batch.Items[0].Error != nil || *batch.Items[0].ContentStatus != "body_available" || batch.Items[0].Card.Content != "Saved body." {
		t.Fatal("success lost original detail or classification")
	}
}

func TestCardBatchStopsWaitingWorkers(t *testing.T) {
	t.Parallel()
	var calls atomic.Int32
	c := batchClient(func(r *http.Request) (*http.Response, error) {
		calls.Add(1)
		return batchResponse(200, `{"code":-1000,"message":"synthetic-test-token Authorization: Bearer secret"}`)
	})
	batch, err := c.GetCardBatch(context.Background(), []string{"a", "b", "c", "d", "e", "f", "g", "h"}, 4)
	if !errors.Is(err, ErrCardBatchIncomplete) || calls.Load() != 3 || batch.Counts != (CardBatchCounts{Total: 8, Error: 3, Skipped: 5}) {
		t.Fatalf("calls=%d counts=%+v err=%v", calls.Load(), batch.Counts, err)
	}
	assertSkippedReasons(t, batch)
	encoded, _ := json.Marshal(batch)
	if strings.Contains(string(encoded), "synthetic-test-token") || strings.Contains(string(encoded), "secret") {
		t.Fatal("API message leaked")
	}
}

func TestCardBatchLateSuccessCannotReopen(t *testing.T) {
	t.Parallel()
	var calls atomic.Int32
	thirdError := make(chan struct{})
	c := batchClient(func(r *http.Request) (*http.Response, error) {
		switch calls.Add(1) {
		case 1:
			<-thirdError
			// Give waiting admissions time to observe the stop before this success.
			time.Sleep(2 * minRequestInterval)
			return cardResponse(r.URL.Query().Get("id"))
		case 4:
			close(thirdError)
		}
		return batchResponse(500, "unavailable")
	})
	batch, err := c.GetCardBatch(context.Background(), []string{"a", "b", "c", "d", "e", "f", "g", "h", "i"}, 4)
	if !errors.Is(err, ErrCardBatchIncomplete) || calls.Load() != 4 || batch.Counts != (CardBatchCounts{Total: 9, OK: 1, Error: 3, Skipped: 5}) {
		t.Fatalf("late success reopened batch: calls=%d counts=%+v err=%v", calls.Load(), batch.Counts, err)
	}
	assertSkippedReasons(t, batch)
}

func assertSkippedReasons(t *testing.T, batch *CardBatch) {
	t.Helper()
	for _, item := range batch.Items {
		if item.Status == "skipped" && (item.Error == nil || item.Error.Code != "consecutive_errors" || item.Card != nil || item.ContentStatus != nil) {
			t.Fatalf("skipped item missing reason: %+v", item)
		}
	}
}

func TestCardBatchSuccessResetsStreak(t *testing.T) {
	t.Parallel()
	var calls atomic.Int32
	c := batchClient(func(r *http.Request) (*http.Response, error) {
		if calls.Add(1)%3 == 0 {
			return cardResponse(r.URL.Query().Get("id"))
		}
		return batchResponse(500, "unavailable")
	})
	batch, err := c.GetCardBatch(context.Background(), []string{"a", "b", "c", "d", "e", "f"}, 1)
	if !errors.Is(err, ErrCardBatchIncomplete) || batch.Counts != (CardBatchCounts{Total: 6, OK: 2, Error: 4}) {
		t.Fatalf("counts=%+v err=%v", batch.Counts, err)
	}
}

func TestCardBatchValidationFailuresStopAndSanitize(t *testing.T) {
	t.Parallel()
	for _, tc := range []struct {
		name      string
		responses []string
		codes     []string
	}{
		{"payloads", []string{`{"code":200,"data":null}`, `{"code":200,"data":{"id":"wrong-secret"}}`, `{"code":200,"data":{"id":"c","content":{}}}`}, []string{"invalid_card_detail", "id_mismatch", "invalid_card_detail"}},
		{"envelopes", []string{`synthetic-test-token`, `{"code":200,"data":["secret"]}`, `{"code":200,"data":{}}`}, []string{"request_failed", "invalid_card_detail", "id_mismatch"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			var calls atomic.Int32
			c := batchClient(func(r *http.Request) (*http.Response, error) {
				n := int(calls.Add(1)) - 1
				if n >= len(tc.responses) {
					return cardResponse(r.URL.Query().Get("id"))
				}
				return batchResponse(200, tc.responses[n])
			})
			batch, err := c.GetCardBatch(context.Background(), []string{"a", "b", "c", "d"}, 1)
			if !errors.Is(err, ErrCardBatchIncomplete) || calls.Load() != 3 || batch.Counts.Skipped != 1 {
				t.Fatalf("calls=%d batch=%+v err=%v", calls.Load(), batch, err)
			}
			for i, code := range tc.codes {
				if batch.Items[i].Error.Code != code {
					t.Fatalf("item %d: %+v", i, batch.Items[i])
				}
			}
			encoded, _ := json.Marshal(batch)
			if strings.Contains(string(encoded), "secret") || strings.Contains(string(encoded), "synthetic-test-token") {
				t.Fatal("response leaked")
			}
		})
	}
}

func TestCardBatchCancellationAndInvalidOptions(t *testing.T) {
	t.Parallel()
	c := batchClient(func(r *http.Request) (*http.Response, error) {
		t.Error("unexpected request")
		return cardResponse("unexpected")
	})
	for _, n := range []int{-1, 0, 5} {
		if batch, err := c.GetCardBatch(context.Background(), []string{"a"}, n); err == nil || batch != nil {
			t.Fatal("invalid workers accepted")
		}
	}
	if batch, err := c.GetCardBatch(context.Background(), []string{" ", ""}, 2); err == nil || batch != nil {
		t.Fatal("empty IDs accepted")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	batch, err := c.GetCardBatch(ctx, []string{"a", "b"}, 2)
	if !errors.Is(err, ErrCardBatchIncomplete) || batch.Counts.Skipped != 2 {
		t.Fatalf("batch=%+v err=%v", batch, err)
	}
	for _, item := range batch.Items {
		if item.Error == nil || item.Error.Code != "canceled" {
			t.Fatal("missing cancellation reason")
		}
	}
}

func TestCardBatchTransportErrorsAreSafe(t *testing.T) {
	t.Parallel()
	c := batchClient(func(r *http.Request) (*http.Response, error) {
		return nil, fmt.Errorf("synthetic-test-token https://user:secret@example.com")
	})
	batch, err := c.GetCardBatch(context.Background(), []string{"a", "b", "c", "d"}, 4)
	if !errors.Is(err, ErrCardBatchIncomplete) || batch.Counts != (CardBatchCounts{Total: 4, Error: 3, Skipped: 1}) {
		t.Fatalf("batch=%+v err=%v", batch, err)
	}
	encoded, _ := json.Marshal(batch)
	if strings.Contains(string(encoded), "secret") || strings.Contains(string(encoded), "synthetic-test-token") {
		t.Fatal("transport error leaked")
	}
}

func TestCardDetailSemanticsUnchangedAndThrottleShared(t *testing.T) {
	t.Parallel()
	var starts []time.Time
	var mu sync.Mutex
	c := batchClient(func(r *http.Request) (*http.Response, error) {
		mu.Lock()
		starts = append(starts, time.Now())
		mu.Unlock()
		return cardResponse("returned-id")
	})
	// Legacy detail continues to return the original detail without ID validation.
	detail, err := c.GetCardDetail("requested-id")
	if err != nil || detail.ID != "returned-id" {
		t.Fatalf("detail=%+v err=%v", detail, err)
	}
	batch, err := c.GetCardBatch(context.Background(), []string{"returned-id"}, 2)
	if err != nil || !reflect.DeepEqual(detail, batch.Items[0].Card) {
		t.Fatalf("batch=%+v err=%v", batch, err)
	}
	if starts[1].Sub(starts[0]) < minRequestInterval-5*time.Millisecond {
		t.Fatal("batch did not share the original Client throttle")
	}
}

func TestCardBatchDoesNotFollowRedirects(t *testing.T) {
	t.Parallel()
	var originalHits atomic.Int32
	original := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		originalHits.Add(1)
		_, _ = io.WriteString(w, "original site must not be fetched")
	}))
	defer original.Close()
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, original.URL, http.StatusFound)
	}))
	defer api.Close()
	c := New(api.URL, "test-token")
	batch, err := c.GetCardBatch(context.Background(), []string{"a"}, 2)
	if !errors.Is(err, ErrCardBatchIncomplete) || originalHits.Load() != 0 || batch.Items[0].Error.HTTPStatus != 302 {
		t.Fatalf("hits=%d batch=%+v err=%v", originalHits.Load(), batch, err)
	}
	if c.httpClient.CheckRedirect != nil {
		t.Fatal("batch changed legacy detail redirect behavior")
	}
}
