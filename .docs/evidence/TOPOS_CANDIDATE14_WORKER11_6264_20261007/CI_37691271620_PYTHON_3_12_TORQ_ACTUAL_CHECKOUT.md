2026-10-07T21:43:24.8808407Z ##[group]Run actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
2026-10-07T21:43:24.8808743Z with:
2026-10-07T21:43:24.8808947Z   repository: ProfJJK-CoChem/CoChem-TORQ
2026-10-07T21:43:24.8809214Z   ref: 79fbb111125e50627a1a2c129888a45496f368d4
2026-10-07T21:43:24.8809778Z   token: ***
2026-10-07T21:43:24.8809983Z   path: .cochem-dependencies/torq
2026-10-07T21:43:24.8810225Z   persist-credentials: false
2026-10-07T21:43:24.8810439Z   ssh-strict: true
2026-10-07T21:43:24.8810631Z   ssh-user: git
2026-10-07T21:43:24.8810821Z   clean: true
2026-10-07T21:43:24.8811015Z   sparse-checkout-cone-mode: true
2026-10-07T21:43:24.8811238Z   fetch-depth: 1
2026-10-07T21:43:24.8811417Z   fetch-tags: false
2026-10-07T21:43:24.8811612Z   show-progress: true
2026-10-07T21:43:24.8811806Z   lfs: false
2026-10-07T21:43:24.8811974Z   submodules: false
2026-10-07T21:43:24.8812164Z   set-safe-directory: true
2026-10-07T21:43:24.8812359Z env:
2026-10-07T21:43:24.8812528Z   TOPOS_REQUIRE_REAL_ENGINES: 1
2026-10-07T21:43:24.8812801Z   TOPOS_EXECUTION_BACKEND: development
2026-10-07T21:43:24.8813027Z   OMP_NUM_THREADS: 1
2026-10-07T21:43:24.8813223Z   OPENBLAS_NUM_THREADS: 1
2026-10-07T21:43:24.8813474Z   pythonLocation: /opt/hostedtoolcache/Python/3.12.15/x64
2026-10-07T21:43:24.8813849Z   PKG_CONFIG_PATH: /opt/hostedtoolcache/Python/3.12.15/x64/lib/pkgconfig
2026-10-07T21:43:24.8814202Z   Python_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.15/x64
2026-10-07T21:43:24.8814520Z   Python2_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.15/x64
2026-10-07T21:43:24.8814847Z   Python3_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.15/x64
2026-10-07T21:43:24.8815166Z   LD_LIBRARY_PATH: /opt/hostedtoolcache/Python/3.12.15/x64/lib
2026-10-07T21:43:24.8815440Z ##[endgroup]
2026-10-07T21:43:24.9523495Z Syncing repository: ProfJJK-CoChem/CoChem-TORQ
2026-10-07T21:43:24.9536585Z ##[group]Getting Git version info
2026-10-07T21:43:24.9537173Z Working directory is '/home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/torq'
2026-10-07T21:43:24.9561748Z [command]/usr/bin/git version
2026-10-07T21:43:24.9597451Z git version 2.55.0
2026-10-07T21:43:24.9613533Z ##[endgroup]
2026-10-07T21:43:24.9625432Z Temporarily overriding HOME='/home/runner/work/_temp/c207c6a9-d024-4fb3-9b84-27ba83707476' before making global git config changes
2026-10-07T21:43:24.9626905Z Adding repository directory to the temporary git global config as a safe directory
2026-10-07T21:43:24.9632282Z [command]/usr/bin/git config --global --add safe.directory /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/torq
2026-10-07T21:43:24.9662640Z ##[group]Initializing the repository
2026-10-07T21:43:24.9667722Z [command]/usr/bin/git init /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/torq
2026-10-07T21:43:25.1041344Z hint: Using 'master' as the name for the initial branch. This default branch name
2026-10-07T21:43:25.1057365Z hint: will change to "main" in Git 3.0. To configure the initial branch name
2026-10-07T21:43:25.1058280Z hint: to use in all of your new repositories, which will suppress this warning,
2026-10-07T21:43:25.1059119Z hint: call:
2026-10-07T21:43:25.1059518Z hint:
2026-10-07T21:43:25.1059997Z hint: 	git config --global init.defaultBranch <name>
2026-10-07T21:43:25.1060529Z hint:
2026-10-07T21:43:25.1061041Z hint: Names commonly chosen instead of 'master' are 'main', 'trunk' and
2026-10-07T21:43:25.1061855Z hint: 'development'. The just-created branch can be renamed via this command:
2026-10-07T21:43:25.1062492Z hint:
2026-10-07T21:43:25.1062895Z hint: 	git branch -m <name>
2026-10-07T21:43:25.1063298Z hint:
2026-10-07T21:43:25.1063840Z hint: Disable this message with "git config set advice.defaultBranchName false"
2026-10-07T21:43:25.1064939Z Initialized empty Git repository in /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/torq/.git/
2026-10-07T21:43:25.1067041Z [command]/usr/bin/git remote add origin https://github.com/ProfJJK-CoChem/CoChem-TORQ
2026-10-07T21:43:25.1140810Z ##[endgroup]
2026-10-07T21:43:25.1141579Z ##[group]Disabling automatic garbage collection
2026-10-07T21:43:25.1142620Z [command]/usr/bin/git config --local gc.auto 0
2026-10-07T21:43:25.1202047Z ##[endgroup]
2026-10-07T21:43:25.1202747Z ##[group]Setting up auth
2026-10-07T21:43:25.1203452Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T21:43:25.1248970Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T21:43:25.1531452Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T21:43:25.1561733Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T21:43:25.1769536Z [command]/usr/bin/git config --local http.https://github.com/.extraheader AUTHORIZATION: basic ***
2026-10-07T21:43:25.1808199Z ##[endgroup]
2026-10-07T21:43:25.1808925Z ##[group]Fetching the repository
2026-10-07T21:43:25.1816671Z [command]/usr/bin/git -c protocol.version=2 fetch --no-tags --prune --no-recurse-submodules --depth=1 origin 79fbb111125e50627a1a2c129888a45496f368d4
2026-10-07T21:43:26.2274494Z From https://github.com/ProfJJK-CoChem/CoChem-TORQ
2026-10-07T21:43:26.2277988Z  * branch            79fbb111125e50627a1a2c129888a45496f368d4 -> FETCH_HEAD
2026-10-07T21:43:26.2280189Z ##[endgroup]
2026-10-07T21:43:26.2280837Z ##[group]Determining the checkout info
2026-10-07T21:43:26.2281583Z ##[endgroup]
2026-10-07T21:43:26.2287621Z [command]/usr/bin/git sparse-checkout disable
2026-10-07T21:43:26.2326444Z [command]/usr/bin/git config --local --unset-all extensions.worktreeConfig
2026-10-07T21:43:26.2351737Z ##[group]Checking out the ref
2026-10-07T21:43:26.2355239Z [command]/usr/bin/git checkout --progress --force 79fbb111125e50627a1a2c129888a45496f368d4
2026-10-07T21:43:26.2693510Z Note: switching to '79fbb111125e50627a1a2c129888a45496f368d4'.
2026-10-07T21:43:26.2696861Z 
2026-10-07T21:43:26.2697381Z You are in 'detached HEAD' state. You can look around, make experimental
2026-10-07T21:43:26.2698156Z changes and commit them, and you can discard any commits you make in this
2026-10-07T21:43:26.2706789Z state without impacting any branches by switching back to a branch.
2026-10-07T21:43:26.2707337Z 
2026-10-07T21:43:26.2707704Z If you want to create a new branch to retain commits you create, you may
2026-10-07T21:43:26.2708424Z do so (now or later) by using -c with the switch command. Example:
2026-10-07T21:43:26.2715281Z 
2026-10-07T21:43:26.2716082Z   git switch -c <new-branch-name>
2026-10-07T21:43:26.2716670Z 
2026-10-07T21:43:26.2717261Z Or undo this operation with:
2026-10-07T21:43:26.2717609Z 
2026-10-07T21:43:26.2717852Z   git switch -
2026-10-07T21:43:26.2718142Z 
2026-10-07T21:43:26.2718529Z Turn off this advice by setting config variable advice.detachedHead to false
2026-10-07T21:43:26.2719040Z 
2026-10-07T21:43:26.2719441Z HEAD is now at 79fbb11 Accept exact reviewed TOPOS handoffs into durable TORQ storage
2026-10-07T21:43:26.2721002Z ##[endgroup]
2026-10-07T21:43:26.2752738Z [command]/usr/bin/git log -1 --format=%H
2026-10-07T21:43:26.2775117Z 79fbb111125e50627a1a2c129888a45496f368d4
2026-10-07T21:43:26.2782404Z ##[group]Removing auth
2026-10-07T21:43:26.2786212Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T21:43:26.2814197Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T21:43:26.3059399Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T21:43:26.3073070Z http.https://github.com/.extraheader
2026-10-07T21:43:26.3104541Z [command]/usr/bin/git config --local --unset-all http.https://github.com/.extraheader
2026-10-07T21:43:26.3121105Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T21:43:26.3313647Z ##[endgroup]
