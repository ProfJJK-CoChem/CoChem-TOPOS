2026-10-07T21:43:16.1794258Z ##[group]Run actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
2026-10-07T21:43:16.1794647Z with:
2026-10-07T21:43:16.1794881Z   repository: ProfJJK-CoChem/CoChem-BASE
2026-10-07T21:43:16.1795156Z   ref: 705b9d54370d5089da286a02b7a1c4afdcbafec1
2026-10-07T21:43:16.1795977Z   token: ***
2026-10-07T21:43:16.1796178Z   path: .cochem-dependencies/base
2026-10-07T21:43:16.1796454Z   persist-credentials: false
2026-10-07T21:43:16.1796678Z   ssh-strict: true
2026-10-07T21:43:16.1796866Z   ssh-user: git
2026-10-07T21:43:16.1797047Z   clean: true
2026-10-07T21:43:16.1797248Z   sparse-checkout-cone-mode: true
2026-10-07T21:43:16.1797480Z   fetch-depth: 1
2026-10-07T21:43:16.1797675Z   fetch-tags: false
2026-10-07T21:43:16.1797873Z   show-progress: true
2026-10-07T21:43:16.1798068Z   lfs: false
2026-10-07T21:43:16.1798247Z   submodules: false
2026-10-07T21:43:16.1798463Z   set-safe-directory: true
2026-10-07T21:43:16.1798725Z env:
2026-10-07T21:43:16.1798921Z   TOPOS_REQUIRE_REAL_ENGINES: 1
2026-10-07T21:43:16.1800468Z   TOPOS_EXECUTION_BACKEND: development
2026-10-07T21:43:16.1800726Z   OMP_NUM_THREADS: 1
2026-10-07T21:43:16.1800934Z   OPENBLAS_NUM_THREADS: 1
2026-10-07T21:43:16.1801206Z   pythonLocation: /opt/hostedtoolcache/Python/3.11.17/x64
2026-10-07T21:43:16.1801616Z   PKG_CONFIG_PATH: /opt/hostedtoolcache/Python/3.11.17/x64/lib/pkgconfig
2026-10-07T21:43:16.1801995Z   Python_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.17/x64
2026-10-07T21:43:16.1802334Z   Python2_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.17/x64
2026-10-07T21:43:16.1802675Z   Python3_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.17/x64
2026-10-07T21:43:16.1803047Z   LD_LIBRARY_PATH: /opt/hostedtoolcache/Python/3.11.17/x64/lib
2026-10-07T21:43:16.1803344Z ##[endgroup]
2026-10-07T21:43:16.2420106Z Syncing repository: ProfJJK-CoChem/CoChem-BASE
2026-10-07T21:43:16.2430716Z ##[group]Getting Git version info
2026-10-07T21:43:16.2431846Z Working directory is '/home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/base'
2026-10-07T21:43:16.2449131Z [command]/usr/bin/git version
2026-10-07T21:43:16.2481601Z git version 2.55.0
2026-10-07T21:43:16.2496885Z ##[endgroup]
2026-10-07T21:43:16.2505107Z Temporarily overriding HOME='/home/runner/work/_temp/c0e71a7c-3098-4778-b325-1e769e9e3030' before making global git config changes
2026-10-07T21:43:16.2506195Z Adding repository directory to the temporary git global config as a safe directory
2026-10-07T21:43:16.2510909Z [command]/usr/bin/git config --global --add safe.directory /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/base
2026-10-07T21:43:16.6344967Z ##[group]Initializing the repository
2026-10-07T21:43:16.6345789Z [command]/usr/bin/git init /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/base
2026-10-07T21:43:16.9750232Z hint: Using 'master' as the name for the initial branch. This default branch name
2026-10-07T21:43:16.9759726Z hint: will change to "main" in Git 3.0. To configure the initial branch name
2026-10-07T21:43:16.9820524Z hint: to use in all of your new repositories, which will suppress this warning,
2026-10-07T21:43:16.9821266Z hint: call:
2026-10-07T21:43:16.9821880Z hint:
2026-10-07T21:43:16.9822277Z hint: 	git config --global init.defaultBranch <name>
2026-10-07T21:43:16.9823061Z hint:
2026-10-07T21:43:16.9823583Z hint: Names commonly chosen instead of 'master' are 'main', 'trunk' and
2026-10-07T21:43:16.9824795Z hint: 'development'. The just-created branch can be renamed via this command:
2026-10-07T21:43:16.9825382Z hint:
2026-10-07T21:43:16.9826016Z hint: 	git branch -m <name>
2026-10-07T21:43:16.9826490Z hint:
2026-10-07T21:43:16.9827205Z hint: Disable this message with "git config set advice.defaultBranchName false"
2026-10-07T21:43:16.9828060Z Initialized empty Git repository in /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/base/.git/
2026-10-07T21:43:16.9830459Z [command]/usr/bin/git remote add origin https://github.com/ProfJJK-CoChem/CoChem-BASE
2026-10-07T21:43:17.2065073Z ##[endgroup]
2026-10-07T21:43:17.2065621Z ##[group]Disabling automatic garbage collection
2026-10-07T21:43:17.2066676Z [command]/usr/bin/git config --local gc.auto 0
2026-10-07T21:43:17.4434813Z ##[endgroup]
2026-10-07T21:43:17.4439732Z ##[group]Setting up auth
2026-10-07T21:43:17.4440171Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T21:43:17.4469893Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T21:43:17.4666001Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T21:43:17.4704300Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T21:43:17.4888142Z [command]/usr/bin/git config --local http.https://github.com/.extraheader AUTHORIZATION: basic ***
2026-10-07T21:43:18.0092735Z ##[endgroup]
2026-10-07T21:43:18.0109848Z ##[group]Fetching the repository
2026-10-07T21:43:18.0110807Z [command]/usr/bin/git -c protocol.version=2 fetch --no-tags --prune --no-recurse-submodules --depth=1 origin 705b9d54370d5089da286a02b7a1c4afdcbafec1
2026-10-07T21:43:19.3286642Z From https://github.com/ProfJJK-CoChem/CoChem-BASE
2026-10-07T21:43:19.3287153Z  * branch            705b9d54370d5089da286a02b7a1c4afdcbafec1 -> FETCH_HEAD
2026-10-07T21:43:19.3288036Z ##[endgroup]
2026-10-07T21:43:19.3288367Z ##[group]Determining the checkout info
2026-10-07T21:43:19.3288735Z ##[endgroup]
2026-10-07T21:43:19.3290195Z [command]/usr/bin/git sparse-checkout disable
2026-10-07T21:43:19.3332816Z [command]/usr/bin/git config --local --unset-all extensions.worktreeConfig
2026-10-07T21:43:19.3386777Z ##[group]Checking out the ref
2026-10-07T21:43:19.3409880Z [command]/usr/bin/git checkout --progress --force 705b9d54370d5089da286a02b7a1c4afdcbafec1
2026-10-07T21:43:19.4905637Z Note: switching to '705b9d54370d5089da286a02b7a1c4afdcbafec1'.
2026-10-07T21:43:19.4906279Z 
2026-10-07T21:43:19.4906852Z You are in 'detached HEAD' state. You can look around, make experimental
2026-10-07T21:43:19.4907455Z changes and commit them, and you can discard any commits you make in this
2026-10-07T21:43:19.4908116Z state without impacting any branches by switching back to a branch.
2026-10-07T21:43:19.4908512Z 
2026-10-07T21:43:19.4908823Z If you want to create a new branch to retain commits you create, you may
2026-10-07T21:43:19.4909518Z do so (now or later) by using -c with the switch command. Example:
2026-10-07T21:43:19.4909889Z 
2026-10-07T21:43:19.4910135Z   git switch -c <new-branch-name>
2026-10-07T21:43:19.4919758Z 
2026-10-07T21:43:19.4919984Z Or undo this operation with:
2026-10-07T21:43:19.4920158Z 
2026-10-07T21:43:19.4920248Z   git switch -
2026-10-07T21:43:19.4920360Z 
2026-10-07T21:43:19.4920548Z Turn off this advice by setting config variable advice.detachedHead to false
2026-10-07T21:43:19.4920839Z 
2026-10-07T21:43:19.4921087Z HEAD is now at 705b9d5 Preserve ordinary CREST installation metadata while auditing source repairs
2026-10-07T21:43:19.4922038Z ##[endgroup]
2026-10-07T21:43:19.4967820Z [command]/usr/bin/git log -1 --format=%H
2026-10-07T21:43:19.4989906Z 705b9d54370d5089da286a02b7a1c4afdcbafec1
2026-10-07T21:43:19.5002163Z ##[group]Removing auth
2026-10-07T21:43:19.5002690Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T21:43:19.5031459Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T21:43:19.5239840Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T21:43:19.5253739Z http.https://github.com/.extraheader
2026-10-07T21:43:19.5257990Z [command]/usr/bin/git config --local --unset-all http.https://github.com/.extraheader
2026-10-07T21:43:19.5287727Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T21:43:19.5471344Z ##[endgroup]
