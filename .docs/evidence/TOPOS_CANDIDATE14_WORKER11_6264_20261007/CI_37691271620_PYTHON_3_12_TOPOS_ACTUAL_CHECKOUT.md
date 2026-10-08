2026-10-07T21:43:04.5074260Z ##[group]Run actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
2026-10-07T21:43:04.5075201Z with:
2026-10-07T21:43:04.5075611Z   persist-credentials: false
2026-10-07T21:43:04.5076088Z   repository: ProfJJK-CoChem/CoChem-TOPOS
2026-10-07T21:43:04.5079533Z   token: ***
2026-10-07T21:43:04.5079936Z   ssh-strict: true
2026-10-07T21:43:04.5080325Z   ssh-user: git
2026-10-07T21:43:04.5080692Z   clean: true
2026-10-07T21:43:04.5081087Z   sparse-checkout-cone-mode: true
2026-10-07T21:43:04.5081539Z   fetch-depth: 1
2026-10-07T21:43:04.5081915Z   fetch-tags: false
2026-10-07T21:43:04.5082306Z   show-progress: true
2026-10-07T21:43:04.5082704Z   lfs: false
2026-10-07T21:43:04.5083068Z   submodules: false
2026-10-07T21:43:04.5083487Z   set-safe-directory: true
2026-10-07T21:43:04.5084092Z env:
2026-10-07T21:43:04.5084488Z   TOPOS_REQUIRE_REAL_ENGINES: 1
2026-10-07T21:43:04.5084945Z   TOPOS_EXECUTION_BACKEND: development
2026-10-07T21:43:04.5085402Z   OMP_NUM_THREADS: 1
2026-10-07T21:43:04.5085803Z   OPENBLAS_NUM_THREADS: 1
2026-10-07T21:43:04.5086256Z ##[endgroup]
2026-10-07T21:43:04.6093270Z Syncing repository: ProfJJK-CoChem/CoChem-TOPOS
2026-10-07T21:43:04.6095866Z ##[group]Getting Git version info
2026-10-07T21:43:04.6097364Z Working directory is '/home/runner/work/CoChem-TOPOS/CoChem-TOPOS'
2026-10-07T21:43:04.6099046Z [command]/usr/bin/git version
2026-10-07T21:43:04.6160760Z git version 2.55.0
2026-10-07T21:43:04.6180156Z ##[endgroup]
2026-10-07T21:43:04.6193946Z Temporarily overriding HOME='/home/runner/work/_temp/c3662627-0612-4877-a4f4-a01d4f033170' before making global git config changes
2026-10-07T21:43:04.6196686Z Adding repository directory to the temporary git global config as a safe directory
2026-10-07T21:43:04.6201117Z [command]/usr/bin/git config --global --add safe.directory /home/runner/work/CoChem-TOPOS/CoChem-TOPOS
2026-10-07T21:43:04.6244267Z Deleting the contents of '/home/runner/work/CoChem-TOPOS/CoChem-TOPOS'
2026-10-07T21:43:04.6253346Z ##[group]Initializing the repository
2026-10-07T21:43:04.6255285Z [command]/usr/bin/git init /home/runner/work/CoChem-TOPOS/CoChem-TOPOS
2026-10-07T21:43:04.6333947Z hint: Using 'master' as the name for the initial branch. This default branch name
2026-10-07T21:43:04.6338494Z hint: will change to "main" in Git 3.0. To configure the initial branch name
2026-10-07T21:43:04.6343724Z hint: to use in all of your new repositories, which will suppress this warning,
2026-10-07T21:43:04.6350599Z hint: call:
2026-10-07T21:43:04.6351509Z hint:
2026-10-07T21:43:04.6352798Z hint: 	git config --global init.defaultBranch <name>
2026-10-07T21:43:04.6353906Z hint:
2026-10-07T21:43:04.6355310Z hint: Names commonly chosen instead of 'master' are 'main', 'trunk' and
2026-10-07T21:43:04.6357184Z hint: 'development'. The just-created branch can be renamed via this command:
2026-10-07T21:43:04.6361409Z hint:
2026-10-07T21:43:04.6362334Z hint: 	git branch -m <name>
2026-10-07T21:43:04.6363670Z hint:
2026-10-07T21:43:04.6364854Z hint: Disable this message with "git config set advice.defaultBranchName false"
2026-10-07T21:43:04.6367581Z Initialized empty Git repository in /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.git/
2026-10-07T21:43:04.6370653Z [command]/usr/bin/git remote add origin https://github.com/ProfJJK-CoChem/CoChem-TOPOS
2026-10-07T21:43:04.6444726Z ##[endgroup]
2026-10-07T21:43:04.6446109Z ##[group]Disabling automatic garbage collection
2026-10-07T21:43:04.6447662Z [command]/usr/bin/git config --local gc.auto 0
2026-10-07T21:43:04.6479694Z ##[endgroup]
2026-10-07T21:43:04.6480804Z ##[group]Setting up auth
2026-10-07T21:43:04.6484670Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T21:43:04.6513246Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T21:43:04.6805586Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T21:43:04.6829759Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T21:43:04.7035273Z [command]/usr/bin/git config --local http.https://github.com/.extraheader AUTHORIZATION: basic ***
2026-10-07T21:43:04.7074681Z ##[endgroup]
2026-10-07T21:43:04.7076711Z ##[group]Fetching the repository
2026-10-07T21:43:04.7083917Z [command]/usr/bin/git -c protocol.version=2 fetch --no-tags --prune --no-recurse-submodules --depth=1 origin +ab66bb8d2b3c4272e8adfcb7cc4fafbebebc9fc3:refs/remotes/pull/1/merge
2026-10-07T21:43:07.2011793Z From https://github.com/ProfJJK-CoChem/CoChem-TOPOS
2026-10-07T21:43:07.2013411Z  * [new ref]         ab66bb8d2b3c4272e8adfcb7cc4fafbebebc9fc3 -> pull/1/merge
2026-10-07T21:43:07.2017257Z ##[endgroup]
2026-10-07T21:43:07.2018063Z ##[group]Determining the checkout info
2026-10-07T21:43:07.2019184Z ##[endgroup]
2026-10-07T21:43:07.2019845Z [command]/usr/bin/git sparse-checkout disable
2026-10-07T21:43:07.2059256Z [command]/usr/bin/git config --local --unset-all extensions.worktreeConfig
2026-10-07T21:43:07.2093876Z ##[group]Checking out the ref
2026-10-07T21:43:07.2097317Z [command]/usr/bin/git checkout --progress --force refs/remotes/pull/1/merge
2026-10-07T21:43:07.3147805Z Note: switching to 'refs/remotes/pull/1/merge'.
2026-10-07T21:43:07.3148676Z 
2026-10-07T21:43:07.3150926Z You are in 'detached HEAD' state. You can look around, make experimental
2026-10-07T21:43:07.3151649Z changes and commit them, and you can discard any commits you make in this
2026-10-07T21:43:07.3152339Z state without impacting any branches by switching back to a branch.
2026-10-07T21:43:07.3152717Z 
2026-10-07T21:43:07.3153040Z If you want to create a new branch to retain commits you create, you may
2026-10-07T21:43:07.3154654Z do so (now or later) by using -c with the switch command. Example:
2026-10-07T21:43:07.3155032Z 
2026-10-07T21:43:07.3155220Z   git switch -c <new-branch-name>
2026-10-07T21:43:07.3155453Z 
2026-10-07T21:43:07.3155640Z Or undo this operation with:
2026-10-07T21:43:07.3155899Z 
2026-10-07T21:43:07.3156037Z   git switch -
2026-10-07T21:43:07.3156257Z 
2026-10-07T21:43:07.3156888Z Turn off this advice by setting config variable advice.detachedHead to false
2026-10-07T21:43:07.3157343Z 
2026-10-07T21:43:07.3157858Z HEAD is now at ab66bb8 Merge 6264cf08e76c37b04f111023161bf46f22c6e98b into 6a01b0f2adb7cff02edda6e339facf3d6f93904d
2026-10-07T21:43:07.3166738Z ##[endgroup]
2026-10-07T21:43:07.3420395Z [command]/usr/bin/git log -1 --format=%H
2026-10-07T21:43:07.3443805Z ab66bb8d2b3c4272e8adfcb7cc4fafbebebc9fc3
2026-10-07T21:43:07.3451277Z ##[group]Removing auth
2026-10-07T21:43:07.3455235Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T21:43:07.3481485Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T21:43:07.3702026Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T21:43:07.3719657Z http.https://github.com/.extraheader
2026-10-07T21:43:07.3725802Z [command]/usr/bin/git config --local --unset-all http.https://github.com/.extraheader
2026-10-07T21:43:07.3872245Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T21:43:07.4092777Z ##[endgroup]
