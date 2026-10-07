2026-10-07T21:43:19.5597305Z ##[group]Run actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
2026-10-07T21:43:19.5597527Z with:
2026-10-07T21:43:19.5597666Z   repository: ProfJJK-CoChem/CoChem-TORQ
2026-10-07T21:43:19.5597844Z   ref: 79fbb111125e50627a1a2c129888a45496f368d4
2026-10-07T21:43:19.5598298Z   token: ***
2026-10-07T21:43:19.5598432Z   path: .cochem-dependencies/torq
2026-10-07T21:43:19.5598597Z   persist-credentials: false
2026-10-07T21:43:19.5598748Z   ssh-strict: true
2026-10-07T21:43:19.5598872Z   ssh-user: git
2026-10-07T21:43:19.5598989Z   clean: true
2026-10-07T21:43:19.5599122Z   sparse-checkout-cone-mode: true
2026-10-07T21:43:19.5599484Z   fetch-depth: 1
2026-10-07T21:43:19.5599605Z   fetch-tags: false
2026-10-07T21:43:19.5599735Z   show-progress: true
2026-10-07T21:43:19.5599861Z   lfs: false
2026-10-07T21:43:19.5599980Z   submodules: false
2026-10-07T21:43:19.5600109Z   set-safe-directory: true
2026-10-07T21:43:19.5600255Z env:
2026-10-07T21:43:19.5600396Z   TOPOS_REQUIRE_REAL_ENGINES: 1
2026-10-07T21:43:19.5600598Z   TOPOS_EXECUTION_BACKEND: development
2026-10-07T21:43:19.5600757Z   OMP_NUM_THREADS: 1
2026-10-07T21:43:19.5600890Z   OPENBLAS_NUM_THREADS: 1
2026-10-07T21:43:19.5601065Z   pythonLocation: /opt/hostedtoolcache/Python/3.11.17/x64
2026-10-07T21:43:19.5601318Z   PKG_CONFIG_PATH: /opt/hostedtoolcache/Python/3.11.17/x64/lib/pkgconfig
2026-10-07T21:43:19.5601563Z   Python_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.17/x64
2026-10-07T21:43:19.5601785Z   Python2_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.17/x64
2026-10-07T21:43:19.5602009Z   Python3_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.17/x64
2026-10-07T21:43:19.5602233Z   LD_LIBRARY_PATH: /opt/hostedtoolcache/Python/3.11.17/x64/lib
2026-10-07T21:43:19.5602427Z ##[endgroup]
2026-10-07T21:43:19.6197966Z Syncing repository: ProfJJK-CoChem/CoChem-TORQ
2026-10-07T21:43:19.6201908Z ##[group]Getting Git version info
2026-10-07T21:43:19.6202558Z Working directory is '/home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/torq'
2026-10-07T21:43:19.6226627Z [command]/usr/bin/git version
2026-10-07T21:43:19.6262001Z git version 2.55.0
2026-10-07T21:43:19.6274623Z ##[endgroup]
2026-10-07T21:43:19.6283731Z Temporarily overriding HOME='/home/runner/work/_temp/4c342749-cea9-4cc4-99e3-7888dd5730ce' before making global git config changes
2026-10-07T21:43:19.6284625Z Adding repository directory to the temporary git global config as a safe directory
2026-10-07T21:43:19.6294047Z [command]/usr/bin/git config --global --add safe.directory /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/torq
2026-10-07T21:43:19.6325641Z ##[group]Initializing the repository
2026-10-07T21:43:19.6326277Z [command]/usr/bin/git init /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/torq
2026-10-07T21:43:19.6356047Z hint: Using 'master' as the name for the initial branch. This default branch name
2026-10-07T21:43:19.6357468Z hint: will change to "main" in Git 3.0. To configure the initial branch name
2026-10-07T21:43:19.6358045Z hint: to use in all of your new repositories, which will suppress this warning,
2026-10-07T21:43:19.6359580Z hint: call:
2026-10-07T21:43:19.6360057Z hint:
2026-10-07T21:43:19.6360448Z hint: 	git config --global init.defaultBranch <name>
2026-10-07T21:43:19.6372074Z hint:
2026-10-07T21:43:19.6372589Z hint: Names commonly chosen instead of 'master' are 'main', 'trunk' and
2026-10-07T21:43:19.6373180Z hint: 'development'. The just-created branch can be renamed via this command:
2026-10-07T21:43:19.6373661Z hint:
2026-10-07T21:43:19.6374001Z hint: 	git branch -m <name>
2026-10-07T21:43:19.6374342Z hint:
2026-10-07T21:43:19.6374780Z hint: Disable this message with "git config set advice.defaultBranchName false"
2026-10-07T21:43:19.6375493Z Initialized empty Git repository in /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/torq/.git/
2026-10-07T21:43:19.6376820Z [command]/usr/bin/git remote add origin https://github.com/ProfJJK-CoChem/CoChem-TORQ
2026-10-07T21:43:19.6400174Z ##[endgroup]
2026-10-07T21:43:19.6405626Z ##[group]Disabling automatic garbage collection
2026-10-07T21:43:19.6406464Z [command]/usr/bin/git config --local gc.auto 0
2026-10-07T21:43:19.6430187Z ##[endgroup]
2026-10-07T21:43:19.6430635Z ##[group]Setting up auth
2026-10-07T21:43:19.6434069Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T21:43:19.6466004Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T21:43:19.6665456Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T21:43:19.6699474Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T21:43:19.6882015Z [command]/usr/bin/git config --local http.https://github.com/.extraheader AUTHORIZATION: basic ***
2026-10-07T21:43:19.6916042Z ##[endgroup]
2026-10-07T21:43:19.6916612Z ##[group]Fetching the repository
2026-10-07T21:43:19.6923237Z [command]/usr/bin/git -c protocol.version=2 fetch --no-tags --prune --no-recurse-submodules --depth=1 origin 79fbb111125e50627a1a2c129888a45496f368d4
2026-10-07T21:43:20.2030398Z From https://github.com/ProfJJK-CoChem/CoChem-TORQ
2026-10-07T21:43:20.2032201Z  * branch            79fbb111125e50627a1a2c129888a45496f368d4 -> FETCH_HEAD
2026-10-07T21:43:20.2041186Z ##[endgroup]
2026-10-07T21:43:20.2041746Z ##[group]Determining the checkout info
2026-10-07T21:43:20.2042291Z ##[endgroup]
2026-10-07T21:43:20.2042675Z [command]/usr/bin/git sparse-checkout disable
2026-10-07T21:43:20.5334679Z [command]/usr/bin/git config --local --unset-all extensions.worktreeConfig
2026-10-07T21:43:20.5361009Z ##[group]Checking out the ref
2026-10-07T21:43:20.5361649Z [command]/usr/bin/git checkout --progress --force 79fbb111125e50627a1a2c129888a45496f368d4
2026-10-07T21:43:20.5685720Z Note: switching to '79fbb111125e50627a1a2c129888a45496f368d4'.
2026-10-07T21:43:20.5695115Z 
2026-10-07T21:43:20.5695551Z You are in 'detached HEAD' state. You can look around, make experimental
2026-10-07T21:43:20.5696116Z changes and commit them, and you can discard any commits you make in this
2026-10-07T21:43:20.5696519Z state without impacting any branches by switching back to a branch.
2026-10-07T21:43:20.5696756Z 
2026-10-07T21:43:20.5696914Z If you want to create a new branch to retain commits you create, you may
2026-10-07T21:43:20.5697311Z do so (now or later) by using -c with the switch command. Example:
2026-10-07T21:43:20.5697534Z 
2026-10-07T21:43:20.5697633Z   git switch -c <new-branch-name>
2026-10-07T21:43:20.5697791Z 
2026-10-07T21:43:20.5697888Z Or undo this operation with:
2026-10-07T21:43:20.5698033Z 
2026-10-07T21:43:20.5698109Z   git switch -
2026-10-07T21:43:20.5698219Z 
2026-10-07T21:43:20.5698407Z Turn off this advice by setting config variable advice.detachedHead to false
2026-10-07T21:43:20.5698988Z 
2026-10-07T21:43:20.5699428Z HEAD is now at 79fbb11 Accept exact reviewed TOPOS handoffs into durable TORQ storage
2026-10-07T21:43:20.5701554Z ##[endgroup]
2026-10-07T21:43:20.5764601Z [command]/usr/bin/git log -1 --format=%H
2026-10-07T21:43:20.5789085Z 79fbb111125e50627a1a2c129888a45496f368d4
2026-10-07T21:43:20.5796651Z ##[group]Removing auth
2026-10-07T21:43:20.5800069Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T21:43:20.5832509Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T21:43:20.6040396Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T21:43:20.6065900Z http.https://github.com/.extraheader
2026-10-07T21:43:20.6067899Z [command]/usr/bin/git config --local --unset-all http.https://github.com/.extraheader
2026-10-07T21:43:20.6093506Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T21:43:20.6283316Z ##[endgroup]
