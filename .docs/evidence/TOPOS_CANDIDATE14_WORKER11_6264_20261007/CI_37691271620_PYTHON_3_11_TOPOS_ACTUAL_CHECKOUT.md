2026-10-07T21:43:03.9756855Z ##[group]Run actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
2026-10-07T21:43:03.9757424Z with:
2026-10-07T21:43:03.9757677Z   persist-credentials: false
2026-10-07T21:43:03.9757982Z   repository: ProfJJK-CoChem/CoChem-TOPOS
2026-10-07T21:43:03.9760256Z   token: ***
2026-10-07T21:43:03.9760497Z   ssh-strict: true
2026-10-07T21:43:03.9760742Z   ssh-user: git
2026-10-07T21:43:03.9760978Z   clean: true
2026-10-07T21:43:03.9761233Z   sparse-checkout-cone-mode: true
2026-10-07T21:43:03.9761525Z   fetch-depth: 1
2026-10-07T21:43:03.9761768Z   fetch-tags: false
2026-10-07T21:43:03.9762018Z   show-progress: true
2026-10-07T21:43:03.9762272Z   lfs: false
2026-10-07T21:43:03.9762503Z   submodules: false
2026-10-07T21:43:03.9762761Z   set-safe-directory: true
2026-10-07T21:43:03.9763116Z env:
2026-10-07T21:43:03.9763383Z   TOPOS_REQUIRE_REAL_ENGINES: 1
2026-10-07T21:43:03.9763681Z   TOPOS_EXECUTION_BACKEND: development
2026-10-07T21:43:03.9763985Z   OMP_NUM_THREADS: 1
2026-10-07T21:43:03.9764242Z   OPENBLAS_NUM_THREADS: 1
2026-10-07T21:43:03.9764533Z ##[endgroup]
2026-10-07T21:43:04.0568461Z Syncing repository: ProfJJK-CoChem/CoChem-TOPOS
2026-10-07T21:43:04.0570444Z ##[group]Getting Git version info
2026-10-07T21:43:04.0571184Z Working directory is '/home/runner/work/CoChem-TOPOS/CoChem-TOPOS'
2026-10-07T21:43:04.0572408Z [command]/usr/bin/git version
2026-10-07T21:43:04.0589891Z git version 2.55.0
2026-10-07T21:43:04.0605065Z ##[endgroup]
2026-10-07T21:43:04.0617590Z Temporarily overriding HOME='/home/runner/work/_temp/ee70a8e0-ba5a-4dcd-b742-a4d6f7ba9e1b' before making global git config changes
2026-10-07T21:43:04.0620569Z Adding repository directory to the temporary git global config as a safe directory
2026-10-07T21:43:04.0622679Z [command]/usr/bin/git config --global --add safe.directory /home/runner/work/CoChem-TOPOS/CoChem-TOPOS
2026-10-07T21:43:04.0672408Z Deleting the contents of '/home/runner/work/CoChem-TOPOS/CoChem-TOPOS'
2026-10-07T21:43:04.0673921Z ##[group]Initializing the repository
2026-10-07T21:43:04.0677167Z [command]/usr/bin/git init /home/runner/work/CoChem-TOPOS/CoChem-TOPOS
2026-10-07T21:43:04.0776489Z hint: Using 'master' as the name for the initial branch. This default branch name
2026-10-07T21:43:04.0777706Z hint: will change to "main" in Git 3.0. To configure the initial branch name
2026-10-07T21:43:04.0778992Z hint: to use in all of your new repositories, which will suppress this warning,
2026-10-07T21:43:04.0780827Z hint: call:
2026-10-07T21:43:04.0782378Z hint:
2026-10-07T21:43:04.0784007Z hint: 	git config --global init.defaultBranch <name>
2026-10-07T21:43:04.0785075Z hint:
2026-10-07T21:43:04.0785858Z hint: Names commonly chosen instead of 'master' are 'main', 'trunk' and
2026-10-07T21:43:04.0787106Z hint: 'development'. The just-created branch can be renamed via this command:
2026-10-07T21:43:04.0788913Z hint:
2026-10-07T21:43:04.0789541Z hint: 	git branch -m <name>
2026-10-07T21:43:04.0789983Z hint:
2026-10-07T21:43:04.0790545Z hint: Disable this message with "git config set advice.defaultBranchName false"
2026-10-07T21:43:04.0791703Z Initialized empty Git repository in /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.git/
2026-10-07T21:43:04.0797142Z [command]/usr/bin/git remote add origin https://github.com/ProfJJK-CoChem/CoChem-TOPOS
2026-10-07T21:43:04.0841157Z ##[endgroup]
2026-10-07T21:43:04.0842081Z ##[group]Disabling automatic garbage collection
2026-10-07T21:43:04.0843044Z [command]/usr/bin/git config --local gc.auto 0
2026-10-07T21:43:04.0863374Z ##[endgroup]
2026-10-07T21:43:04.0864277Z ##[group]Setting up auth
2026-10-07T21:43:04.0867992Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T21:43:04.0895062Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T21:43:04.1197364Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T21:43:04.1226721Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T21:43:04.1417761Z [command]/usr/bin/git config --local http.https://github.com/.extraheader AUTHORIZATION: basic ***
2026-10-07T21:43:04.1453900Z ##[endgroup]
2026-10-07T21:43:04.1454561Z ##[group]Fetching the repository
2026-10-07T21:43:04.1462987Z [command]/usr/bin/git -c protocol.version=2 fetch --no-tags --prune --no-recurse-submodules --depth=1 origin +ab66bb8d2b3c4272e8adfcb7cc4fafbebebc9fc3:refs/remotes/pull/1/merge
2026-10-07T21:43:04.9442293Z From https://github.com/ProfJJK-CoChem/CoChem-TOPOS
2026-10-07T21:43:04.9444806Z  * [new ref]         ab66bb8d2b3c4272e8adfcb7cc4fafbebebc9fc3 -> pull/1/merge
2026-10-07T21:43:04.9447853Z ##[endgroup]
2026-10-07T21:43:04.9448926Z ##[group]Determining the checkout info
2026-10-07T21:43:04.9450412Z ##[endgroup]
2026-10-07T21:43:04.9457192Z [command]/usr/bin/git sparse-checkout disable
2026-10-07T21:43:05.0910047Z [command]/usr/bin/git config --local --unset-all extensions.worktreeConfig
2026-10-07T21:43:05.0940703Z ##[group]Checking out the ref
2026-10-07T21:43:05.0943448Z [command]/usr/bin/git checkout --progress --force refs/remotes/pull/1/merge
2026-10-07T21:43:05.1446533Z Note: switching to 'refs/remotes/pull/1/merge'.
2026-10-07T21:43:05.1447629Z 
2026-10-07T21:43:05.1448215Z You are in 'detached HEAD' state. You can look around, make experimental
2026-10-07T21:43:05.1449561Z changes and commit them, and you can discard any commits you make in this
2026-10-07T21:43:05.1450844Z state without impacting any branches by switching back to a branch.
2026-10-07T21:43:05.1451523Z 
2026-10-07T21:43:05.1452078Z If you want to create a new branch to retain commits you create, you may
2026-10-07T21:43:05.1453566Z do so (now or later) by using -c with the switch command. Example:
2026-10-07T21:43:05.1454243Z 
2026-10-07T21:43:05.1454631Z   git switch -c <new-branch-name>
2026-10-07T21:43:05.1455133Z 
2026-10-07T21:43:05.1455506Z Or undo this operation with:
2026-10-07T21:43:05.1459675Z 
2026-10-07T21:43:05.1460350Z   git switch -
2026-10-07T21:43:05.1461061Z 
2026-10-07T21:43:05.1461736Z Turn off this advice by setting config variable advice.detachedHead to false
2026-10-07T21:43:05.1462603Z 
2026-10-07T21:43:05.1463487Z HEAD is now at ab66bb8 Merge 6264cf08e76c37b04f111023161bf46f22c6e98b into 6a01b0f2adb7cff02edda6e339facf3d6f93904d
2026-10-07T21:43:05.1466667Z ##[endgroup]
2026-10-07T21:43:05.1509802Z [command]/usr/bin/git log -1 --format=%H
2026-10-07T21:43:05.1533281Z ab66bb8d2b3c4272e8adfcb7cc4fafbebebc9fc3
2026-10-07T21:43:05.1540748Z ##[group]Removing auth
2026-10-07T21:43:05.1543540Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T21:43:05.1571040Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T21:43:05.1755144Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T21:43:05.1794744Z http.https://github.com/.extraheader
2026-10-07T21:43:05.1801385Z [command]/usr/bin/git config --local --unset-all http.https://github.com/.extraheader
2026-10-07T21:43:05.1875682Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T21:43:05.2140993Z ##[endgroup]
