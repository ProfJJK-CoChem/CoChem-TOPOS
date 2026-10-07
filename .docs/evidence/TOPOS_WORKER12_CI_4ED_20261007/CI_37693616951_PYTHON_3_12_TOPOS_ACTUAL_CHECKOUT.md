2026-10-07T22:03:13.5378443Z ##[group]Run actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
2026-10-07T22:03:13.5378855Z with:
2026-10-07T22:03:13.5378986Z   persist-credentials: false
2026-10-07T22:03:13.5379147Z   repository: ProfJJK-CoChem/CoChem-TOPOS
2026-10-07T22:03:13.5380617Z   token: ***
2026-10-07T22:03:13.5380740Z   ssh-strict: true
2026-10-07T22:03:13.5380860Z   ssh-user: git
2026-10-07T22:03:13.5381105Z   clean: true
2026-10-07T22:03:13.5381241Z   sparse-checkout-cone-mode: true
2026-10-07T22:03:13.5381395Z   fetch-depth: 1
2026-10-07T22:03:13.5381523Z   fetch-tags: false
2026-10-07T22:03:13.5381652Z   show-progress: true
2026-10-07T22:03:13.5381792Z   lfs: false
2026-10-07T22:03:13.5381901Z   submodules: false
2026-10-07T22:03:13.5382030Z   set-safe-directory: true
2026-10-07T22:03:13.5382242Z env:
2026-10-07T22:03:13.5382379Z   TOPOS_REQUIRE_REAL_ENGINES: 1
2026-10-07T22:03:13.5382539Z   TOPOS_EXECUTION_BACKEND: development
2026-10-07T22:03:13.5382690Z   OMP_NUM_THREADS: 1
2026-10-07T22:03:13.5382817Z   OPENBLAS_NUM_THREADS: 1
2026-10-07T22:03:13.5382993Z ##[endgroup]
2026-10-07T22:03:13.6205595Z Syncing repository: ProfJJK-CoChem/CoChem-TOPOS
2026-10-07T22:03:13.6207011Z ##[group]Getting Git version info
2026-10-07T22:03:13.6208291Z Working directory is '/home/runner/work/CoChem-TOPOS/CoChem-TOPOS'
2026-10-07T22:03:13.6209248Z [command]/usr/bin/git version
2026-10-07T22:03:13.6264434Z git version 2.55.0
2026-10-07T22:03:13.6278337Z ##[endgroup]
2026-10-07T22:03:13.6289103Z Temporarily overriding HOME='/home/runner/work/_temp/7fb7b22d-7912-4417-bb85-edb70f9e4830' before making global git config changes
2026-10-07T22:03:13.6290157Z Adding repository directory to the temporary git global config as a safe directory
2026-10-07T22:03:13.6293674Z [command]/usr/bin/git config --global --add safe.directory /home/runner/work/CoChem-TOPOS/CoChem-TOPOS
2026-10-07T22:03:13.7203007Z Deleting the contents of '/home/runner/work/CoChem-TOPOS/CoChem-TOPOS'
2026-10-07T22:03:13.7204701Z ##[group]Initializing the repository
2026-10-07T22:03:13.7207390Z [command]/usr/bin/git init /home/runner/work/CoChem-TOPOS/CoChem-TOPOS
2026-10-07T22:03:13.7311755Z hint: Using 'master' as the name for the initial branch. This default branch name
2026-10-07T22:03:13.7316258Z hint: will change to "main" in Git 3.0. To configure the initial branch name
2026-10-07T22:03:13.7323762Z hint: to use in all of your new repositories, which will suppress this warning,
2026-10-07T22:03:13.7332215Z hint: call:
2026-10-07T22:03:13.7332527Z hint:
2026-10-07T22:03:13.7332900Z hint: 	git config --global init.defaultBranch <name>
2026-10-07T22:03:13.7333255Z hint:
2026-10-07T22:03:13.7333599Z hint: Names commonly chosen instead of 'master' are 'main', 'trunk' and
2026-10-07T22:03:13.7334105Z hint: 'development'. The just-created branch can be renamed via this command:
2026-10-07T22:03:13.7334551Z hint:
2026-10-07T22:03:13.7334802Z hint: 	git branch -m <name>
2026-10-07T22:03:13.7335082Z hint:
2026-10-07T22:03:13.7335432Z hint: Disable this message with "git config set advice.defaultBranchName false"
2026-10-07T22:03:13.7336112Z Initialized empty Git repository in /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.git/
2026-10-07T22:03:13.7339710Z [command]/usr/bin/git remote add origin https://github.com/ProfJJK-CoChem/CoChem-TOPOS
2026-10-07T22:03:13.7373153Z ##[endgroup]
2026-10-07T22:03:13.7373405Z ##[group]Disabling automatic garbage collection
2026-10-07T22:03:13.7373717Z [command]/usr/bin/git config --local gc.auto 0
2026-10-07T22:03:13.7411485Z ##[endgroup]
2026-10-07T22:03:13.7411904Z ##[group]Setting up auth
2026-10-07T22:03:13.7412326Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T22:03:13.7432257Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T22:03:13.7729860Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T22:03:13.7756637Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T22:03:13.7944310Z [command]/usr/bin/git config --local http.https://github.com/.extraheader AUTHORIZATION: basic ***
2026-10-07T22:03:13.7979756Z ##[endgroup]
2026-10-07T22:03:13.7980450Z ##[group]Fetching the repository
2026-10-07T22:03:13.7987001Z [command]/usr/bin/git -c protocol.version=2 fetch --no-tags --prune --no-recurse-submodules --depth=1 origin +d6c85dbbf9c0f0d65a1242dab7000bfbbd6822f9:refs/remotes/pull/1/merge
2026-10-07T22:03:15.2043187Z From https://github.com/ProfJJK-CoChem/CoChem-TOPOS
2026-10-07T22:03:15.2046413Z  * [new ref]         d6c85dbbf9c0f0d65a1242dab7000bfbbd6822f9 -> pull/1/merge
2026-10-07T22:03:15.2048276Z ##[endgroup]
2026-10-07T22:03:15.2048641Z ##[group]Determining the checkout info
2026-10-07T22:03:15.2049009Z ##[endgroup]
2026-10-07T22:03:15.2049270Z [command]/usr/bin/git sparse-checkout disable
2026-10-07T22:03:15.2092162Z [command]/usr/bin/git config --local --unset-all extensions.worktreeConfig
2026-10-07T22:03:15.2115561Z ##[group]Checking out the ref
2026-10-07T22:03:15.2118294Z [command]/usr/bin/git checkout --progress --force refs/remotes/pull/1/merge
2026-10-07T22:03:15.2612597Z Note: switching to 'refs/remotes/pull/1/merge'.
2026-10-07T22:03:15.2612989Z 
2026-10-07T22:03:15.2613218Z You are in 'detached HEAD' state. You can look around, make experimental
2026-10-07T22:03:15.2613667Z changes and commit them, and you can discard any commits you make in this
2026-10-07T22:03:15.2614090Z state without impacting any branches by switching back to a branch.
2026-10-07T22:03:15.2614337Z 
2026-10-07T22:03:15.2614546Z If you want to create a new branch to retain commits you create, you may
2026-10-07T22:03:15.2615216Z do so (now or later) by using -c with the switch command. Example:
2026-10-07T22:03:15.2615446Z 
2026-10-07T22:03:15.2615571Z   git switch -c <new-branch-name>
2026-10-07T22:03:15.2615728Z 
2026-10-07T22:03:15.2615829Z Or undo this operation with:
2026-10-07T22:03:15.2615999Z 
2026-10-07T22:03:15.2616080Z   git switch -
2026-10-07T22:03:15.2616203Z 
2026-10-07T22:03:15.2616410Z Turn off this advice by setting config variable advice.detachedHead to false
2026-10-07T22:03:15.2616674Z 
2026-10-07T22:03:15.2617006Z HEAD is now at d6c85db Merge 4ed689a309d868bdfcb2ffec26ea257ca1788db4 into 6a01b0f2adb7cff02edda6e339facf3d6f93904d
2026-10-07T22:03:15.2625664Z ##[endgroup]
2026-10-07T22:03:15.2673333Z [command]/usr/bin/git log -1 --format=%H
2026-10-07T22:03:15.2695444Z d6c85dbbf9c0f0d65a1242dab7000bfbbd6822f9
2026-10-07T22:03:15.2705593Z ##[group]Removing auth
2026-10-07T22:03:15.2708794Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T22:03:15.2736248Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T22:03:15.2930665Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T22:03:15.2958316Z http.https://github.com/.extraheader
2026-10-07T22:03:15.2965738Z [command]/usr/bin/git config --local --unset-all http.https://github.com/.extraheader
2026-10-07T22:03:15.2994618Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T22:03:15.3174749Z ##[endgroup]
