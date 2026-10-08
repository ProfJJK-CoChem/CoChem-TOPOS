2026-10-07T21:43:20.8535408Z ##[group]Run actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
2026-10-07T21:43:20.8535770Z with:
2026-10-07T21:43:20.8535967Z   repository: ProfJJK-CoChem/CoChem-BASE
2026-10-07T21:43:20.8536230Z   ref: 705b9d54370d5089da286a02b7a1c4afdcbafec1
2026-10-07T21:43:20.8536984Z   token: ***
2026-10-07T21:43:20.8537181Z   path: .cochem-dependencies/base
2026-10-07T21:43:20.8537428Z   persist-credentials: false
2026-10-07T21:43:20.8537640Z   ssh-strict: true
2026-10-07T21:43:20.8537819Z   ssh-user: git
2026-10-07T21:43:20.8537991Z   clean: true
2026-10-07T21:43:20.8538182Z   sparse-checkout-cone-mode: true
2026-10-07T21:43:20.8538400Z   fetch-depth: 1
2026-10-07T21:43:20.8538580Z   fetch-tags: false
2026-10-07T21:43:20.8538776Z   show-progress: true
2026-10-07T21:43:20.8538965Z   lfs: false
2026-10-07T21:43:20.8539140Z   submodules: false
2026-10-07T21:43:20.8539327Z   set-safe-directory: true
2026-10-07T21:43:20.8539533Z env:
2026-10-07T21:43:20.8539705Z   TOPOS_REQUIRE_REAL_ENGINES: 1
2026-10-07T21:43:20.8539996Z   TOPOS_EXECUTION_BACKEND: development
2026-10-07T21:43:20.8540226Z   OMP_NUM_THREADS: 1
2026-10-07T21:43:20.8540434Z   OPENBLAS_NUM_THREADS: 1
2026-10-07T21:43:20.8540683Z   pythonLocation: /opt/hostedtoolcache/Python/3.12.15/x64
2026-10-07T21:43:20.8541058Z   PKG_CONFIG_PATH: /opt/hostedtoolcache/Python/3.12.15/x64/lib/pkgconfig
2026-10-07T21:43:20.8541426Z   Python_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.15/x64
2026-10-07T21:43:20.8541742Z   Python2_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.15/x64
2026-10-07T21:43:20.8542047Z   Python3_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.15/x64
2026-10-07T21:43:20.8542379Z   LD_LIBRARY_PATH: /opt/hostedtoolcache/Python/3.12.15/x64/lib
2026-10-07T21:43:20.8542649Z ##[endgroup]
2026-10-07T21:43:20.9281860Z Syncing repository: ProfJJK-CoChem/CoChem-BASE
2026-10-07T21:43:20.9285381Z ##[group]Getting Git version info
2026-10-07T21:43:20.9286260Z Working directory is '/home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/base'
2026-10-07T21:43:20.9317783Z [command]/usr/bin/git version
2026-10-07T21:43:20.9354022Z git version 2.55.0
2026-10-07T21:43:20.9370769Z ##[endgroup]
2026-10-07T21:43:20.9382563Z Temporarily overriding HOME='/home/runner/work/_temp/cadf9729-c4b5-4187-98e3-86752482054f' before making global git config changes
2026-10-07T21:43:20.9383826Z Adding repository directory to the temporary git global config as a safe directory
2026-10-07T21:43:20.9388334Z [command]/usr/bin/git config --global --add safe.directory /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/base
2026-10-07T21:43:21.0772042Z ##[group]Initializing the repository
2026-10-07T21:43:21.0773018Z [command]/usr/bin/git init /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/base
2026-10-07T21:43:21.8021827Z hint: Using 'master' as the name for the initial branch. This default branch name
2026-10-07T21:43:21.8022570Z hint: will change to "main" in Git 3.0. To configure the initial branch name
2026-10-07T21:43:21.8024988Z hint: to use in all of your new repositories, which will suppress this warning,
2026-10-07T21:43:21.8026561Z hint: call:
2026-10-07T21:43:21.8027022Z hint:
2026-10-07T21:43:21.8027508Z hint: 	git config --global init.defaultBranch <name>
2026-10-07T21:43:21.8028132Z hint:
2026-10-07T21:43:21.8030199Z hint: Names commonly chosen instead of 'master' are 'main', 'trunk' and
2026-10-07T21:43:21.8031657Z hint: 'development'. The just-created branch can be renamed via this command:
2026-10-07T21:43:21.8032340Z hint:
2026-10-07T21:43:21.8032743Z hint: 	git branch -m <name>
2026-10-07T21:43:21.8033207Z hint:
2026-10-07T21:43:21.8033765Z hint: Disable this message with "git config set advice.defaultBranchName false"
2026-10-07T21:43:21.8034814Z Initialized empty Git repository in /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/base/.git/
2026-10-07T21:43:21.8039273Z [command]/usr/bin/git remote add origin https://github.com/ProfJJK-CoChem/CoChem-BASE
2026-10-07T21:43:22.0613214Z ##[endgroup]
2026-10-07T21:43:22.0613938Z ##[group]Disabling automatic garbage collection
2026-10-07T21:43:22.0620302Z [command]/usr/bin/git config --local gc.auto 0
2026-10-07T21:43:22.1300970Z ##[endgroup]
2026-10-07T21:43:22.1301661Z ##[group]Setting up auth
2026-10-07T21:43:22.1309044Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T21:43:22.1342731Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T21:43:22.1547601Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T21:43:22.1575971Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T21:43:22.1783087Z [command]/usr/bin/git config --local http.https://github.com/.extraheader AUTHORIZATION: basic ***
2026-10-07T21:43:22.5602483Z ##[endgroup]
2026-10-07T21:43:22.5603391Z ##[group]Fetching the repository
2026-10-07T21:43:22.5615197Z [command]/usr/bin/git -c protocol.version=2 fetch --no-tags --prune --no-recurse-submodules --depth=1 origin 705b9d54370d5089da286a02b7a1c4afdcbafec1
2026-10-07T21:43:24.6313712Z From https://github.com/ProfJJK-CoChem/CoChem-BASE
2026-10-07T21:43:24.6314704Z  * branch            705b9d54370d5089da286a02b7a1c4afdcbafec1 -> FETCH_HEAD
2026-10-07T21:43:24.6348471Z ##[endgroup]
2026-10-07T21:43:24.6350515Z ##[group]Determining the checkout info
2026-10-07T21:43:24.6351150Z ##[endgroup]
2026-10-07T21:43:24.6351562Z [command]/usr/bin/git sparse-checkout disable
2026-10-07T21:43:24.6392249Z [command]/usr/bin/git config --local --unset-all extensions.worktreeConfig
2026-10-07T21:43:24.6420383Z ##[group]Checking out the ref
2026-10-07T21:43:24.6421081Z [command]/usr/bin/git checkout --progress --force 705b9d54370d5089da286a02b7a1c4afdcbafec1
2026-10-07T21:43:24.8045104Z Note: switching to '705b9d54370d5089da286a02b7a1c4afdcbafec1'.
2026-10-07T21:43:24.8053382Z 
2026-10-07T21:43:24.8057090Z You are in 'detached HEAD' state. You can look around, make experimental
2026-10-07T21:43:24.8057835Z changes and commit them, and you can discard any commits you make in this
2026-10-07T21:43:24.8058554Z state without impacting any branches by switching back to a branch.
2026-10-07T21:43:24.8059002Z 
2026-10-07T21:43:24.8059321Z If you want to create a new branch to retain commits you create, you may
2026-10-07T21:43:24.8059971Z do so (now or later) by using -c with the switch command. Example:
2026-10-07T21:43:24.8060391Z 
2026-10-07T21:43:24.8060633Z   git switch -c <new-branch-name>
2026-10-07T21:43:24.8060943Z 
2026-10-07T21:43:24.8061163Z Or undo this operation with:
2026-10-07T21:43:24.8061458Z 
2026-10-07T21:43:24.8061637Z   git switch -
2026-10-07T21:43:24.8061874Z 
2026-10-07T21:43:24.8062221Z Turn off this advice by setting config variable advice.detachedHead to false
2026-10-07T21:43:24.8062918Z 
2026-10-07T21:43:24.8063338Z HEAD is now at 705b9d5 Preserve ordinary CREST installation metadata while auditing source repairs
2026-10-07T21:43:24.8071747Z ##[endgroup]
2026-10-07T21:43:24.8106733Z [command]/usr/bin/git log -1 --format=%H
2026-10-07T21:43:24.8129232Z 705b9d54370d5089da286a02b7a1c4afdcbafec1
2026-10-07T21:43:24.8136543Z ##[group]Removing auth
2026-10-07T21:43:24.8139905Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T21:43:24.8170070Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T21:43:24.8387203Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T21:43:24.8408399Z http.https://github.com/.extraheader
2026-10-07T21:43:24.8418216Z [command]/usr/bin/git config --local --unset-all http.https://github.com/.extraheader
2026-10-07T21:43:24.8447219Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T21:43:24.8651026Z ##[endgroup]
