2026-10-07T22:03:12.3139762Z ##[group]Run actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
2026-10-07T22:03:12.3141033Z with:
2026-10-07T22:03:12.3141526Z   persist-credentials: false
2026-10-07T22:03:12.3142134Z   repository: ProfJJK-CoChem/CoChem-TOPOS
2026-10-07T22:03:12.3146712Z   token: ***
2026-10-07T22:03:12.3147177Z   ssh-strict: true
2026-10-07T22:03:12.3147637Z   ssh-user: git
2026-10-07T22:03:12.3148080Z   clean: true
2026-10-07T22:03:12.3148744Z   sparse-checkout-cone-mode: true
2026-10-07T22:03:12.3149350Z   fetch-depth: 1
2026-10-07T22:03:12.3149820Z   fetch-tags: false
2026-10-07T22:03:12.3150299Z   show-progress: true
2026-10-07T22:03:12.3150793Z   lfs: false
2026-10-07T22:03:12.3151233Z   submodules: false
2026-10-07T22:03:12.3151793Z   set-safe-directory: true
2026-10-07T22:03:12.3152597Z env:
2026-10-07T22:03:12.3153078Z   TOPOS_REQUIRE_REAL_ENGINES: 1
2026-10-07T22:03:12.3153707Z   TOPOS_EXECUTION_BACKEND: development
2026-10-07T22:03:12.3154320Z   OMP_NUM_THREADS: 1
2026-10-07T22:03:12.3154822Z   OPENBLAS_NUM_THREADS: 1
2026-10-07T22:03:12.3155374Z ##[endgroup]
2026-10-07T22:03:12.5230698Z Syncing repository: ProfJJK-CoChem/CoChem-TOPOS
2026-10-07T22:03:12.5233837Z ##[group]Getting Git version info
2026-10-07T22:03:12.5235345Z Working directory is '/home/runner/work/CoChem-TOPOS/CoChem-TOPOS'
2026-10-07T22:03:12.5237447Z [command]/usr/bin/git version
2026-10-07T22:03:12.5238733Z git version 2.55.0
2026-10-07T22:03:12.5241836Z ##[endgroup]
2026-10-07T22:03:12.5248397Z Temporarily overriding HOME='/home/runner/work/_temp/7e57bcd8-6449-44b5-bfa8-9cb05db2f32c' before making global git config changes
2026-10-07T22:03:12.5251927Z Adding repository directory to the temporary git global config as a safe directory
2026-10-07T22:03:12.5254479Z [command]/usr/bin/git config --global --add safe.directory /home/runner/work/CoChem-TOPOS/CoChem-TOPOS
2026-10-07T22:03:12.5258445Z Deleting the contents of '/home/runner/work/CoChem-TOPOS/CoChem-TOPOS'
2026-10-07T22:03:12.5261015Z ##[group]Initializing the repository
2026-10-07T22:03:12.5262604Z [command]/usr/bin/git init /home/runner/work/CoChem-TOPOS/CoChem-TOPOS
2026-10-07T22:03:12.5264633Z hint: Using 'master' as the name for the initial branch. This default branch name
2026-10-07T22:03:12.5266759Z hint: will change to "main" in Git 3.0. To configure the initial branch name
2026-10-07T22:03:12.5268997Z hint: to use in all of your new repositories, which will suppress this warning,
2026-10-07T22:03:12.5270607Z hint: call:
2026-10-07T22:03:12.5271360Z hint:
2026-10-07T22:03:12.5272310Z hint: 	git config --global init.defaultBranch <name>
2026-10-07T22:03:12.5273560Z hint:
2026-10-07T22:03:12.5274718Z hint: Names commonly chosen instead of 'master' are 'main', 'trunk' and
2026-10-07T22:03:12.5276691Z hint: 'development'. The just-created branch can be renamed via this command:
2026-10-07T22:03:12.5278344Z hint:
2026-10-07T22:03:12.5280370Z hint: 	git branch -m <name>
2026-10-07T22:03:12.5281331Z hint:
2026-10-07T22:03:12.5282568Z hint: Disable this message with "git config set advice.defaultBranchName false"
2026-10-07T22:03:12.5284952Z Initialized empty Git repository in /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.git/
2026-10-07T22:03:12.5288404Z [command]/usr/bin/git remote add origin https://github.com/ProfJJK-CoChem/CoChem-TOPOS
2026-10-07T22:03:12.5292049Z ##[endgroup]
2026-10-07T22:03:12.5293505Z ##[group]Disabling automatic garbage collection
2026-10-07T22:03:12.5294803Z [command]/usr/bin/git config --local gc.auto 0
2026-10-07T22:03:12.5297485Z ##[endgroup]
2026-10-07T22:03:12.5299098Z ##[group]Setting up auth
2026-10-07T22:03:12.5300700Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T22:03:12.5305326Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T22:03:12.5349387Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T22:03:12.5399943Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T22:03:12.5625179Z [command]/usr/bin/git config --local http.https://github.com/.extraheader AUTHORIZATION: basic ***
2026-10-07T22:03:12.5681652Z ##[endgroup]
2026-10-07T22:03:12.5683993Z ##[group]Fetching the repository
2026-10-07T22:03:12.5693360Z [command]/usr/bin/git -c protocol.version=2 fetch --no-tags --prune --no-recurse-submodules --depth=1 origin +d6c85dbbf9c0f0d65a1242dab7000bfbbd6822f9:refs/remotes/pull/1/merge
2026-10-07T22:03:13.5859309Z From https://github.com/ProfJJK-CoChem/CoChem-TOPOS
2026-10-07T22:03:13.5864571Z  * [new ref]         d6c85dbbf9c0f0d65a1242dab7000bfbbd6822f9 -> pull/1/merge
2026-10-07T22:03:13.5877167Z ##[endgroup]
2026-10-07T22:03:13.5879849Z ##[group]Determining the checkout info
2026-10-07T22:03:13.5882461Z ##[endgroup]
2026-10-07T22:03:13.5884198Z [command]/usr/bin/git sparse-checkout disable
2026-10-07T22:03:13.5934876Z [command]/usr/bin/git config --local --unset-all extensions.worktreeConfig
2026-10-07T22:03:13.5967236Z ##[group]Checking out the ref
2026-10-07T22:03:13.5970429Z [command]/usr/bin/git checkout --progress --force refs/remotes/pull/1/merge
2026-10-07T22:03:13.6682339Z Note: switching to 'refs/remotes/pull/1/merge'.
2026-10-07T22:03:13.6683422Z 
2026-10-07T22:03:13.6684216Z You are in 'detached HEAD' state. You can look around, make experimental
2026-10-07T22:03:13.6686120Z changes and commit them, and you can discard any commits you make in this
2026-10-07T22:03:13.6687913Z state without impacting any branches by switching back to a branch.
2026-10-07T22:03:13.6689331Z 
2026-10-07T22:03:13.6690116Z If you want to create a new branch to retain commits you create, you may
2026-10-07T22:03:13.6692398Z do so (now or later) by using -c with the switch command. Example:
2026-10-07T22:03:13.6693618Z 
2026-10-07T22:03:13.6694213Z   git switch -c <new-branch-name>
2026-10-07T22:03:13.6695057Z 
2026-10-07T22:03:13.6695617Z Or undo this operation with:
2026-10-07T22:03:13.6696453Z 
2026-10-07T22:03:13.6696974Z   git switch -
2026-10-07T22:03:13.6697628Z 
2026-10-07T22:03:13.6699212Z Turn off this advice by setting config variable advice.detachedHead to false
2026-10-07T22:03:13.6701484Z 
2026-10-07T22:03:13.6703998Z HEAD is now at d6c85db Merge 4ed689a309d868bdfcb2ffec26ea257ca1788db4 into 6a01b0f2adb7cff02edda6e339facf3d6f93904d
2026-10-07T22:03:13.6725450Z ##[endgroup]
2026-10-07T22:03:13.6767844Z [command]/usr/bin/git log -1 --format=%H
2026-10-07T22:03:13.6792993Z d6c85dbbf9c0f0d65a1242dab7000bfbbd6822f9
2026-10-07T22:03:13.6809291Z ##[group]Removing auth
2026-10-07T22:03:13.6820477Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T22:03:13.6847609Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T22:03:13.7082089Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T22:03:13.7114054Z http.https://github.com/.extraheader
2026-10-07T22:03:13.7131446Z [command]/usr/bin/git config --local --unset-all http.https://github.com/.extraheader
2026-10-07T22:03:13.7167384Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T22:03:13.7386983Z ##[endgroup]
