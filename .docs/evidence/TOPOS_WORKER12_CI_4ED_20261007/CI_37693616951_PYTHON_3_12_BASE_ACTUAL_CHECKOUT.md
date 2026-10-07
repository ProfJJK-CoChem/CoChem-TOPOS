2026-10-07T22:03:26.2876130Z ##[group]Run actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
2026-10-07T22:03:26.2876363Z with:
2026-10-07T22:03:26.2876495Z   repository: ProfJJK-CoChem/CoChem-BASE
2026-10-07T22:03:26.2876663Z   ref: 705b9d54370d5089da286a02b7a1c4afdcbafec1
2026-10-07T22:03:26.2877120Z   token: ***
2026-10-07T22:03:26.2877264Z   path: .cochem-dependencies/base
2026-10-07T22:03:26.2877415Z   persist-credentials: false
2026-10-07T22:03:26.2877553Z   ssh-strict: true
2026-10-07T22:03:26.2877670Z   ssh-user: git
2026-10-07T22:03:26.2877779Z   clean: true
2026-10-07T22:03:26.2877898Z   sparse-checkout-cone-mode: true
2026-10-07T22:03:26.2878039Z   fetch-depth: 1
2026-10-07T22:03:26.2878158Z   fetch-tags: false
2026-10-07T22:03:26.2878275Z   show-progress: true
2026-10-07T22:03:26.2878391Z   lfs: false
2026-10-07T22:03:26.2878501Z   submodules: false
2026-10-07T22:03:26.2878619Z   set-safe-directory: true
2026-10-07T22:03:26.2878748Z env:
2026-10-07T22:03:26.2878861Z   TOPOS_REQUIRE_REAL_ENGINES: 1
2026-10-07T22:03:26.2879058Z   TOPOS_EXECUTION_BACKEND: development
2026-10-07T22:03:26.2879203Z   OMP_NUM_THREADS: 1
2026-10-07T22:03:26.2879327Z   OPENBLAS_NUM_THREADS: 1
2026-10-07T22:03:26.2879491Z   pythonLocation: /opt/hostedtoolcache/Python/3.12.15/x64
2026-10-07T22:03:26.2879747Z   PKG_CONFIG_PATH: /opt/hostedtoolcache/Python/3.12.15/x64/lib/pkgconfig
2026-10-07T22:03:26.2879984Z   Python_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.15/x64
2026-10-07T22:03:26.2880194Z   Python2_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.15/x64
2026-10-07T22:03:26.2880404Z   Python3_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.15/x64
2026-10-07T22:03:26.2880624Z   LD_LIBRARY_PATH: /opt/hostedtoolcache/Python/3.12.15/x64/lib
2026-10-07T22:03:26.2880800Z ##[endgroup]
2026-10-07T22:03:26.3504303Z Syncing repository: ProfJJK-CoChem/CoChem-BASE
2026-10-07T22:03:26.3504985Z ##[group]Getting Git version info
2026-10-07T22:03:26.3505509Z Working directory is '/home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/base'
2026-10-07T22:03:26.3527841Z [command]/usr/bin/git version
2026-10-07T22:03:26.3558779Z git version 2.55.0
2026-10-07T22:03:26.3570768Z ##[endgroup]
2026-10-07T22:03:26.3579857Z Temporarily overriding HOME='/home/runner/work/_temp/a8376966-ecc1-45db-ab77-379325d4185f' before making global git config changes
2026-10-07T22:03:26.3580685Z Adding repository directory to the temporary git global config as a safe directory
2026-10-07T22:03:26.3584645Z [command]/usr/bin/git config --global --add safe.directory /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/base
2026-10-07T22:03:26.5653467Z ##[group]Initializing the repository
2026-10-07T22:03:26.5654163Z [command]/usr/bin/git init /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/base
2026-10-07T22:03:27.2441277Z hint: Using 'master' as the name for the initial branch. This default branch name
2026-10-07T22:03:27.2444998Z hint: will change to "main" in Git 3.0. To configure the initial branch name
2026-10-07T22:03:27.2445563Z hint: to use in all of your new repositories, which will suppress this warning,
2026-10-07T22:03:27.2446065Z hint: call:
2026-10-07T22:03:27.2446335Z hint:
2026-10-07T22:03:27.2446670Z hint: 	git config --global init.defaultBranch <name>
2026-10-07T22:03:27.2447647Z hint:
2026-10-07T22:03:27.2448025Z hint: Names commonly chosen instead of 'master' are 'main', 'trunk' and
2026-10-07T22:03:27.2449316Z hint: 'development'. The just-created branch can be renamed via this command:
2026-10-07T22:03:27.2450129Z hint:
2026-10-07T22:03:27.2450395Z hint: 	git branch -m <name>
2026-10-07T22:03:27.2450686Z hint:
2026-10-07T22:03:27.2451233Z hint: Disable this message with "git config set advice.defaultBranchName false"
2026-10-07T22:03:27.2451968Z Initialized empty Git repository in /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/base/.git/
2026-10-07T22:03:27.2473267Z [command]/usr/bin/git remote add origin https://github.com/ProfJJK-CoChem/CoChem-BASE
2026-10-07T22:03:27.4233621Z ##[endgroup]
2026-10-07T22:03:27.4234176Z ##[group]Disabling automatic garbage collection
2026-10-07T22:03:27.4235208Z [command]/usr/bin/git config --local gc.auto 0
2026-10-07T22:03:27.5252974Z ##[endgroup]
2026-10-07T22:03:27.5253630Z ##[group]Setting up auth
2026-10-07T22:03:27.5254166Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T22:03:27.5283270Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T22:03:27.5465653Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T22:03:27.5491330Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T22:03:27.5664247Z [command]/usr/bin/git config --local http.https://github.com/.extraheader AUTHORIZATION: basic ***
2026-10-07T22:03:27.7196601Z ##[endgroup]
2026-10-07T22:03:27.7197075Z ##[group]Fetching the repository
2026-10-07T22:03:27.7197654Z [command]/usr/bin/git -c protocol.version=2 fetch --no-tags --prune --no-recurse-submodules --depth=1 origin 705b9d54370d5089da286a02b7a1c4afdcbafec1
2026-10-07T22:03:31.6784424Z From https://github.com/ProfJJK-CoChem/CoChem-BASE
2026-10-07T22:03:31.6785123Z  * branch            705b9d54370d5089da286a02b7a1c4afdcbafec1 -> FETCH_HEAD
2026-10-07T22:03:31.6804055Z ##[endgroup]
2026-10-07T22:03:31.6826640Z ##[group]Determining the checkout info
2026-10-07T22:03:31.6829319Z ##[endgroup]
2026-10-07T22:03:31.6829635Z [command]/usr/bin/git sparse-checkout disable
2026-10-07T22:03:32.0074523Z [command]/usr/bin/git config --local --unset-all extensions.worktreeConfig
2026-10-07T22:03:32.1522072Z ##[group]Checking out the ref
2026-10-07T22:03:32.1530709Z [command]/usr/bin/git checkout --progress --force 705b9d54370d5089da286a02b7a1c4afdcbafec1
2026-10-07T22:03:32.3685133Z Note: switching to '705b9d54370d5089da286a02b7a1c4afdcbafec1'.
2026-10-07T22:03:32.3688352Z 
2026-10-07T22:03:32.3688906Z You are in 'detached HEAD' state. You can look around, make experimental
2026-10-07T22:03:32.3689567Z changes and commit them, and you can discard any commits you make in this
2026-10-07T22:03:32.3720490Z state without impacting any branches by switching back to a branch.
2026-10-07T22:03:32.3720907Z 
2026-10-07T22:03:32.3721362Z If you want to create a new branch to retain commits you create, you may
2026-10-07T22:03:32.3721901Z do so (now or later) by using -c with the switch command. Example:
2026-10-07T22:03:32.3722238Z 
2026-10-07T22:03:32.3722456Z   git switch -c <new-branch-name>
2026-10-07T22:03:32.3722724Z 
2026-10-07T22:03:32.3722937Z Or undo this operation with:
2026-10-07T22:03:32.3723196Z 
2026-10-07T22:03:32.3723392Z   git switch -
2026-10-07T22:03:32.3723613Z 
2026-10-07T22:03:32.3723913Z Turn off this advice by setting config variable advice.detachedHead to false
2026-10-07T22:03:32.3731276Z 
2026-10-07T22:03:32.3736463Z HEAD is now at 705b9d5 Preserve ordinary CREST installation metadata while auditing source repairs
2026-10-07T22:03:32.3737859Z ##[endgroup]
2026-10-07T22:03:32.3763577Z [command]/usr/bin/git log -1 --format=%H
2026-10-07T22:03:32.3794183Z 705b9d54370d5089da286a02b7a1c4afdcbafec1
2026-10-07T22:03:32.3808730Z ##[group]Removing auth
2026-10-07T22:03:32.3823725Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T22:03:32.3916953Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T22:03:32.4208777Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T22:03:32.4247250Z http.https://github.com/.extraheader
2026-10-07T22:03:32.4257179Z [command]/usr/bin/git config --local --unset-all http.https://github.com/.extraheader
2026-10-07T22:03:32.5789907Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T22:03:32.5982912Z ##[endgroup]
