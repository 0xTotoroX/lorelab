// [INPUT]: 合成的 folder/list HTTP 响应。
// [OUTPUT]: 相同记录去重、顺序保留与冲突拒绝的边界检查。
// [POS]: 文件夹读取契约测试，不访问真实账号。
// [PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md。
package client

import (
	"encoding/json"
	"net/http"
	"reflect"
	"strings"
	"testing"
)

func TestListFoldersDeduplicatesIdenticalRows(t *testing.T) {
	parentA, parentB := "parent", "parent"
	first := Folder{ID: "inbox", Name: "Uncategorized", NestedName: "Uncategorized", Uncategorized: true}
	child := Folder{ID: "child", Name: "Notes", ParentID: &parentA}
	duplicateChild := child
	duplicateChild.ParentID = &parentB
	input := []Folder{first, child, first, duplicateChild}
	c := batchClient(func(r *http.Request) (*http.Response, error) {
		if r.Method != http.MethodGet || r.URL.Path != "/c/api/cli/folder/list" {
			t.Fatal("unexpected folder request")
		}
		data, _ := json.Marshal(input)
		body, _ := json.Marshal(APIResponse{Code: 200, Data: data})
		return batchResponse(200, string(body))
	})
	got, err := c.ListFolders()
	if err != nil || !reflect.DeepEqual(got, []Folder{first, child}) {
		t.Fatalf("deduplication changed first occurrence or order: got=%v err=%v", got, err)
	}
}

func TestListFoldersRejectsConflictingDuplicates(t *testing.T) {
	parent := "protected-parent"
	for _, changed := range []Folder{
		{ID: "same", Name: "GitHub"},
		{ID: "same", Name: "Notes", ParentID: &parent},
		{ID: "same", Name: "Notes", Uncategorized: true},
	} {
		c := batchClient(func(_ *http.Request) (*http.Response, error) {
			data, _ := json.Marshal([]Folder{{ID: "same", Name: "Notes"}, changed})
			body, _ := json.Marshal(APIResponse{Code: 200, Data: data})
			return batchResponse(200, string(body))
		})
		got, err := c.ListFolders()
		if got != nil || err == nil || !strings.Contains(err.Error(), "conflicting entries") {
			t.Fatalf("conflicting folder accepted: got=%v err=%v", got, err)
		}
	}
}
