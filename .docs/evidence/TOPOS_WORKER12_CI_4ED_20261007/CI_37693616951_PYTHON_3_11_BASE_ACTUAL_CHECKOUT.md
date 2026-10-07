2026-10-07T22:03:24.4853276Z ##[group]Run actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
2026-10-07T22:03:24.4853689Z with:
2026-10-07T22:03:24.4853917Z   repository: ProfJJK-CoChem/CoChem-BASE
2026-10-07T22:03:24.4854228Z   ref: 705b9d54370d5089da286a02b7a1c4afdcbafec1
2026-10-07T22:03:24.4854876Z   token: ***
2026-10-07T22:03:24.4855105Z   path: .cochem-dependencies/base
2026-10-07T22:03:24.4855381Z   persist-credentials: false
2026-10-07T22:03:24.4855635Z   ssh-strict: true
2026-10-07T22:03:24.4855843Z   ssh-user: git
2026-10-07T22:03:24.4856053Z   clean: true
2026-10-07T22:03:24.4856286Z   sparse-checkout-cone-mode: true
2026-10-07T22:03:24.4856551Z   fetch-depth: 1
2026-10-07T22:03:24.4856753Z   fetch-tags: false
2026-10-07T22:03:24.4856968Z   show-progress: true
2026-10-07T22:03:24.4857189Z   lfs: false
2026-10-07T22:03:24.4857382Z   submodules: false
2026-10-07T22:03:24.4857599Z   set-safe-directory: true
2026-10-07T22:03:24.4857841Z env:
2026-10-07T22:03:24.4858038Z   TOPOS_REQUIRE_REAL_ENGINES: 1
2026-10-07T22:03:24.4858330Z   TOPOS_EXECUTION_BACKEND: development
2026-10-07T22:03:24.4859078Z   OMP_NUM_THREADS: 1
2026-10-07T22:03:24.4859316Z   OPENBLAS_NUM_THREADS: 1
2026-10-07T22:03:24.4859618Z   pythonLocation: /opt/hostedtoolcache/Python/3.11.16/x64
2026-10-07T22:03:24.4860068Z   PKG_CONFIG_PATH: /opt/hostedtoolcache/Python/3.11.16/x64/lib/pkgconfig
2026-10-07T22:03:24.4860501Z   Python_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.16/x64
2026-10-07T22:03:24.4860890Z   Python2_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.16/x64
2026-10-07T22:03:24.4861275Z   Python3_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.16/x64
2026-10-07T22:03:24.4861669Z   LD_LIBRARY_PATH: /opt/hostedtoolcache/Python/3.11.16/x64/lib
2026-10-07T22:03:24.4862009Z ##[endgroup]
2026-10-07T22:03:24.5739039Z Syncing repository: ProfJJK-CoChem/CoChem-BASE
2026-10-07T22:03:24.5744868Z ##[group]Getting Git version info
2026-10-07T22:03:24.5746052Z Working directory is '/home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/base'
2026-10-07T22:03:24.5789825Z [command]/usr/bin/git version
2026-10-07T22:03:24.5830838Z git version 2.55.0
2026-10-07T22:03:24.5852687Z ##[endgroup]
2026-10-07T22:03:24.5866053Z Temporarily overriding HOME='/home/runner/work/_temp/1cd6c602-44b0-4e62-8158-cf5d6f133e50' before making global git config changes
2026-10-07T22:03:24.5867639Z Adding repository directory to the temporary git global config as a safe directory
2026-10-07T22:03:24.5880508Z [command]/usr/bin/git config --global --add safe.directory /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/base
2026-10-07T22:03:24.5920611Z ##[group]Initializing the repository
2026-10-07T22:03:24.5923962Z [command]/usr/bin/git init /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/base
2026-10-07T22:03:24.6141604Z hint: Using 'master' as the name for the initial branch. This default branch name
2026-10-07T22:03:24.6142764Z hint: will change to "main" in Git 3.0. To configure the initial branch name
2026-10-07T22:03:24.6143732Z hint: to use in all of your new repositories, which will suppress this warning,
2026-10-07T22:03:24.6144542Z hint: call:
2026-10-07T22:03:24.6145039Z hint:
2026-10-07T22:03:24.6145678Z hint: 	git config --global init.defaultBranch <name>
2026-10-07T22:03:24.6146426Z hint:
2026-10-07T22:03:24.6147150Z hint: Names commonly chosen instead of 'master' are 'main', 'trunk' and
2026-10-07T22:03:24.6149256Z hint: 'development'. The just-created branch can be renamed via this command:
2026-10-07T22:03:24.6150181Z hint:
2026-10-07T22:03:24.6150732Z hint: 	git branch -m <name>
2026-10-07T22:03:24.6151522Z hint:
2026-10-07T22:03:24.6152234Z hint: Disable this message with "git config set advice.defaultBranchName false"
2026-10-07T22:03:24.6153558Z Initialized empty Git repository in /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/base/.git/
2026-10-07T22:03:24.6159122Z [command]/usr/bin/git remote add origin https://github.com/ProfJJK-CoChem/CoChem-BASE
2026-10-07T22:03:24.6599793Z ##[endgroup]
2026-10-07T22:03:24.6600825Z ##[group]Disabling automatic garbage collection
2026-10-07T22:03:24.6602259Z [command]/usr/bin/git config --local gc.auto 0
2026-10-07T22:03:24.6649513Z ##[endgroup]
2026-10-07T22:03:24.6650304Z ##[group]Setting up auth
2026-10-07T22:03:24.6651119Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T22:03:24.6673867Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T22:03:24.6910896Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T22:03:24.6942816Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T22:03:24.7182975Z [command]/usr/bin/git config --local http.https://github.com/.extraheader AUTHORIZATION: basic ***
2026-10-07T22:03:24.7222719Z ##[endgroup]
2026-10-07T22:03:24.7223604Z ##[group]Fetching the repository
2026-10-07T22:03:24.7232553Z [command]/usr/bin/git -c protocol.version=2 fetch --no-tags --prune --no-recurse-submodules --depth=1 origin 705b9d54370d5089da286a02b7a1c4afdcbafec1
2026-10-07T22:03:26.2534503Z From https://github.com/ProfJJK-CoChem/CoChem-BASE
2026-10-07T22:03:26.2537946Z  * branch            705b9d54370d5089da286a02b7a1c4afdcbafec1 -> FETCH_HEAD
2026-10-07T22:03:26.2546676Z ##[endgroup]
2026-10-07T22:03:26.2547654Z ##[group]Determining the checkout info
2026-10-07T22:03:26.2548926Z ##[endgroup]
2026-10-07T22:03:26.2550350Z [command]/usr/bin/git sparse-checkout disable
2026-10-07T22:03:26.2601533Z [command]/usr/bin/git config --local --unset-all extensions.worktreeConfig
2026-10-07T22:03:26.2625927Z ##[group]Checking out the ref
2026-10-07T22:03:26.2631744Z [command]/usr/bin/git checkout --progress --force 705b9d54370d5089da286a02b7a1c4afdcbafec1
2026-10-07T22:03:26.4621812Z Note: switching to '705b9d54370d5089da286a02b7a1c4afdcbafec1'.
2026-10-07T22:03:26.4629286Z 
2026-10-07T22:03:26.4639232Z You are in 'detached HEAD' state. You can look around, make experimental
2026-10-07T22:03:26.4640408Z changes and commit them, and you can discard any commits you make in this
2026-10-07T22:03:26.4641503Z state without impacting any branches by switching back to a branch.
2026-10-07T22:03:26.4642300Z 
2026-10-07T22:03:26.4642771Z If you want to create a new branch to retain commits you create, you may
2026-10-07T22:03:26.4643816Z do so (now or later) by using -c with the switch command. Example:
2026-10-07T22:03:26.4644665Z 
2026-10-07T22:03:26.4677357Z   git switch -c <new-branch-name>
2026-10-07T22:03:26.4694335Z 
2026-10-07T22:03:26.4694881Z Or undo this operation with:
2026-10-07T22:03:26.4695428Z 
2026-10-07T22:03:26.4695787Z   git switch -
2026-10-07T22:03:26.4696208Z 
2026-10-07T22:03:26.4696772Z Turn off this advice by setting config variable advice.detachedHead to false
2026-10-07T22:03:26.4697557Z 
2026-10-07T22:03:26.4698248Z HEAD is now at 705b9d5 Preserve ordinary CREST installation metadata while auditing source repairs
2026-10-07T22:03:26.4700973Z ##[endgroup]
2026-10-07T22:03:26.4715787Z [command]/usr/bin/git log -1 --format=%H
2026-10-07T22:03:26.4742822Z 705b9d54370d5089da286a02b7a1c4afdcbafec1
2026-10-07T22:03:26.4751016Z ##[group]Removing auth
2026-10-07T22:03:26.4756577Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T22:03:26.4791014Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T22:03:26.5036780Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T22:03:26.5064579Z http.https://github.com/.extraheader
2026-10-07T22:03:26.5078828Z [command]/usr/bin/git config --local --unset-all http.https://github.com/.extraheader
2026-10-07T22:03:26.5113378Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T22:03:26.5340857Z ##[endgroup]
