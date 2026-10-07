2026-10-07T22:03:26.5489456Z ##[group]Run actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
2026-10-07T22:03:26.5489862Z with:
2026-10-07T22:03:26.5490093Z   repository: ProfJJK-CoChem/CoChem-TORQ
2026-10-07T22:03:26.5490420Z   ref: 79fbb111125e50627a1a2c129888a45496f368d4
2026-10-07T22:03:26.5491058Z   token: ***
2026-10-07T22:03:26.5491293Z   path: .cochem-dependencies/torq
2026-10-07T22:03:26.5491576Z   persist-credentials: false
2026-10-07T22:03:26.5491824Z   ssh-strict: true
2026-10-07T22:03:26.5492038Z   ssh-user: git
2026-10-07T22:03:26.5492237Z   clean: true
2026-10-07T22:03:26.5492464Z   sparse-checkout-cone-mode: true
2026-10-07T22:03:26.5492723Z   fetch-depth: 1
2026-10-07T22:03:26.5492931Z   fetch-tags: false
2026-10-07T22:03:26.5493150Z   show-progress: true
2026-10-07T22:03:26.5493366Z   lfs: false
2026-10-07T22:03:26.5493560Z   submodules: false
2026-10-07T22:03:26.5493784Z   set-safe-directory: true
2026-10-07T22:03:26.5494011Z env:
2026-10-07T22:03:26.5494209Z   TOPOS_REQUIRE_REAL_ENGINES: 1
2026-10-07T22:03:26.5494506Z   TOPOS_EXECUTION_BACKEND: development
2026-10-07T22:03:26.5494773Z   OMP_NUM_THREADS: 1
2026-10-07T22:03:26.5494999Z   OPENBLAS_NUM_THREADS: 1
2026-10-07T22:03:26.5495297Z   pythonLocation: /opt/hostedtoolcache/Python/3.11.16/x64
2026-10-07T22:03:26.5495743Z   PKG_CONFIG_PATH: /opt/hostedtoolcache/Python/3.11.16/x64/lib/pkgconfig
2026-10-07T22:03:26.5496170Z   Python_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.16/x64
2026-10-07T22:03:26.5496557Z   Python2_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.16/x64
2026-10-07T22:03:26.5496942Z   Python3_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.16/x64
2026-10-07T22:03:26.5497334Z   LD_LIBRARY_PATH: /opt/hostedtoolcache/Python/3.11.16/x64/lib
2026-10-07T22:03:26.5497667Z ##[endgroup]
2026-10-07T22:03:26.6366539Z Syncing repository: ProfJJK-CoChem/CoChem-TORQ
2026-10-07T22:03:26.6373924Z ##[group]Getting Git version info
2026-10-07T22:03:26.6375110Z Working directory is '/home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/torq'
2026-10-07T22:03:26.6420181Z [command]/usr/bin/git version
2026-10-07T22:03:26.6468766Z git version 2.55.0
2026-10-07T22:03:26.6490757Z ##[endgroup]
2026-10-07T22:03:26.6505577Z Temporarily overriding HOME='/home/runner/work/_temp/4ed9f6c2-35f9-4184-b026-0129a62dc4dd' before making global git config changes
2026-10-07T22:03:26.6507240Z Adding repository directory to the temporary git global config as a safe directory
2026-10-07T22:03:26.6512497Z [command]/usr/bin/git config --global --add safe.directory /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/torq
2026-10-07T22:03:26.6548846Z ##[group]Initializing the repository
2026-10-07T22:03:26.6555157Z [command]/usr/bin/git init /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/torq
2026-10-07T22:03:26.6601260Z hint: Using 'master' as the name for the initial branch. This default branch name
2026-10-07T22:03:26.6603481Z hint: will change to "main" in Git 3.0. To configure the initial branch name
2026-10-07T22:03:26.6609876Z hint: to use in all of your new repositories, which will suppress this warning,
2026-10-07T22:03:26.6610881Z hint: call:
2026-10-07T22:03:26.6611439Z hint:
2026-10-07T22:03:26.6612096Z hint: 	git config --global init.defaultBranch <name>
2026-10-07T22:03:26.6613078Z hint:
2026-10-07T22:03:26.6613791Z hint: Names commonly chosen instead of 'master' are 'main', 'trunk' and
2026-10-07T22:03:26.6615809Z hint: 'development'. The just-created branch can be renamed via this command:
2026-10-07T22:03:26.6616898Z hint:
2026-10-07T22:03:26.6617450Z hint: 	git branch -m <name>
2026-10-07T22:03:26.6618080Z hint:
2026-10-07T22:03:26.6619186Z hint: Disable this message with "git config set advice.defaultBranchName false"
2026-10-07T22:03:26.6620580Z Initialized empty Git repository in /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/torq/.git/
2026-10-07T22:03:26.6622839Z [command]/usr/bin/git remote add origin https://github.com/ProfJJK-CoChem/CoChem-TORQ
2026-10-07T22:03:26.6657445Z ##[endgroup]
2026-10-07T22:03:26.6658116Z ##[group]Disabling automatic garbage collection
2026-10-07T22:03:26.6659353Z [command]/usr/bin/git config --local gc.auto 0
2026-10-07T22:03:26.6725199Z ##[endgroup]
2026-10-07T22:03:26.6726220Z ##[group]Setting up auth
2026-10-07T22:03:26.6736093Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T22:03:26.6777181Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T22:03:26.7119992Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T22:03:26.7164052Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T22:03:26.7527650Z [command]/usr/bin/git config --local http.https://github.com/.extraheader AUTHORIZATION: basic ***
2026-10-07T22:03:26.7595648Z ##[endgroup]
2026-10-07T22:03:26.7596719Z ##[group]Fetching the repository
2026-10-07T22:03:26.7606459Z [command]/usr/bin/git -c protocol.version=2 fetch --no-tags --prune --no-recurse-submodules --depth=1 origin 79fbb111125e50627a1a2c129888a45496f368d4
2026-10-07T22:03:27.3811138Z From https://github.com/ProfJJK-CoChem/CoChem-TORQ
2026-10-07T22:03:27.3819939Z  * branch            79fbb111125e50627a1a2c129888a45496f368d4 -> FETCH_HEAD
2026-10-07T22:03:27.3821946Z ##[endgroup]
2026-10-07T22:03:27.3822686Z ##[group]Determining the checkout info
2026-10-07T22:03:27.3823545Z ##[endgroup]
2026-10-07T22:03:27.3825656Z [command]/usr/bin/git sparse-checkout disable
2026-10-07T22:03:27.3867124Z [command]/usr/bin/git config --local --unset-all extensions.worktreeConfig
2026-10-07T22:03:27.3895124Z ##[group]Checking out the ref
2026-10-07T22:03:27.3900175Z [command]/usr/bin/git checkout --progress --force 79fbb111125e50627a1a2c129888a45496f368d4
2026-10-07T22:03:27.4323786Z Note: switching to '79fbb111125e50627a1a2c129888a45496f368d4'.
2026-10-07T22:03:27.4338753Z 
2026-10-07T22:03:27.4358139Z You are in 'detached HEAD' state. You can look around, make experimental
2026-10-07T22:03:27.4382653Z changes and commit them, and you can discard any commits you make in this
2026-10-07T22:03:27.4398123Z state without impacting any branches by switching back to a branch.
2026-10-07T22:03:27.4410370Z 
2026-10-07T22:03:27.4431450Z If you want to create a new branch to retain commits you create, you may
2026-10-07T22:03:27.4445799Z do so (now or later) by using -c with the switch command. Example:
2026-10-07T22:03:27.4461389Z 
2026-10-07T22:03:27.4491546Z   git switch -c <new-branch-name>
2026-10-07T22:03:27.4509115Z 
2026-10-07T22:03:27.4516600Z Or undo this operation with:
2026-10-07T22:03:27.4534286Z 
2026-10-07T22:03:27.4546325Z   git switch -
2026-10-07T22:03:27.4546709Z 
2026-10-07T22:03:27.4547183Z Turn off this advice by setting config variable advice.detachedHead to false
2026-10-07T22:03:27.4547876Z 
2026-10-07T22:03:27.4548401Z HEAD is now at 79fbb11 Accept exact reviewed TOPOS handoffs into durable TORQ storage
2026-10-07T22:03:27.4550703Z ##[endgroup]
2026-10-07T22:03:27.4552231Z [command]/usr/bin/git log -1 --format=%H
2026-10-07T22:03:27.4552896Z 79fbb111125e50627a1a2c129888a45496f368d4
2026-10-07T22:03:27.4554486Z ##[group]Removing auth
2026-10-07T22:03:27.4555258Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T22:03:27.4557604Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T22:03:27.4772990Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T22:03:27.4797744Z http.https://github.com/.extraheader
2026-10-07T22:03:27.4805650Z [command]/usr/bin/git config --local --unset-all http.https://github.com/.extraheader
2026-10-07T22:03:27.4839254Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T22:03:27.5066895Z ##[endgroup]
