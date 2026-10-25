# Design and acceptance

Use `ls-tree -r -t -z` for a resolved tree ID or `ls-files --stage -z` for the
index; reject unresolved merge stages. Parse bytes, including tabs/newlines
inside filenames, without asking the host filesystem about a target.
Infer index directory entries. Batch-check symlink object sizes, then batch-read
only the mode-120000 blob bodies. No filters, hooks, fetches or checkout.

Resolve one path component at a time. Dot and parent components are evaluated
after preceding directory symlinks have expanded. A `(link, pending suffix)`
state detects ordinary cycles without misclassifying a finite repeated directory
link; an independent hop limit bounds expanding cycles. A submodule is an
opaque boundary. Return every link's result, not just the first error.

Acceptance includes real temporary Git indexes/commits on Windows without OS
symlinks, native Git follow-symlink comparisons, a Linux filesystem oracle for
dot/parent resolution, no-index-mutation assertions, alternate indexes,
subdirectory invocation, staged-versus-committed differences, special-name tree
objects, explicit malformed input failures, and bounded cycles.

Independent review found that Git 2.56 `cat-file --follow-symlinks` treats a
target containing `d/./../file` differently from POSIX resolution, while
`d/../file` agrees. The implementation retains component-wise POSIX semantics;
Linux CI verifies the disputed class against actual symlinks. Windows Git's
index protects NTFS-incompatible paths, so a special-name fixture is built as
a tree object using mktree, without disabling protection or materializing it.
