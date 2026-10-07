2026-10-07T22:03:32.7689737Z ##[group]Run actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
2026-10-07T22:03:32.7690107Z with:
2026-10-07T22:03:32.7690298Z   repository: ProfJJK-CoChem/CoChem-TORQ
2026-10-07T22:03:32.7690551Z   ref: 79fbb111125e50627a1a2c129888a45496f368d4
2026-10-07T22:03:32.7691323Z   token: ***
2026-10-07T22:03:32.7691509Z   path: .cochem-dependencies/torq
2026-10-07T22:03:32.7691743Z   persist-credentials: false
2026-10-07T22:03:32.7691954Z   ssh-strict: true
2026-10-07T22:03:32.7692140Z   ssh-user: git
2026-10-07T22:03:32.7692312Z   clean: true
2026-10-07T22:03:32.7692505Z   sparse-checkout-cone-mode: true
2026-10-07T22:03:32.7692727Z   fetch-depth: 1
2026-10-07T22:03:32.7692908Z   fetch-tags: false
2026-10-07T22:03:32.7693096Z   show-progress: true
2026-10-07T22:03:32.7693283Z   lfs: false
2026-10-07T22:03:32.7693454Z   submodules: false
2026-10-07T22:03:32.7693651Z   set-safe-directory: true
2026-10-07T22:03:32.7693853Z env:
2026-10-07T22:03:32.7694029Z   TOPOS_REQUIRE_REAL_ENGINES: 1
2026-10-07T22:03:32.7694329Z   TOPOS_EXECUTION_BACKEND: development
2026-10-07T22:03:32.7694565Z   OMP_NUM_THREADS: 1
2026-10-07T22:03:32.7694765Z   OPENBLAS_NUM_THREADS: 1
2026-10-07T22:03:32.7695025Z   pythonLocation: /opt/hostedtoolcache/Python/3.12.15/x64
2026-10-07T22:03:32.7695404Z   PKG_CONFIG_PATH: /opt/hostedtoolcache/Python/3.12.15/x64/lib/pkgconfig
2026-10-07T22:03:32.7695770Z   Python_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.15/x64
2026-10-07T22:03:32.7696103Z   Python2_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.15/x64
2026-10-07T22:03:32.7696442Z   Python3_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.15/x64
2026-10-07T22:03:32.7696780Z   LD_LIBRARY_PATH: /opt/hostedtoolcache/Python/3.12.15/x64/lib
2026-10-07T22:03:32.7697070Z ##[endgroup]
2026-10-07T22:03:32.8311400Z Syncing repository: ProfJJK-CoChem/CoChem-TORQ
2026-10-07T22:03:32.8315617Z ##[group]Getting Git version info
2026-10-07T22:03:32.8316233Z Working directory is '/home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/torq'
2026-10-07T22:03:32.8340172Z [command]/usr/bin/git version
2026-10-07T22:03:32.8373773Z git version 2.55.0
2026-10-07T22:03:32.8386916Z ##[endgroup]
2026-10-07T22:03:32.8403387Z Temporarily overriding HOME='/home/runner/work/_temp/0f3d56a3-628b-48d1-a99a-a5c7793ba700' before making global git config changes
2026-10-07T22:03:32.8404415Z Adding repository directory to the temporary git global config as a safe directory
2026-10-07T22:03:32.8406819Z [command]/usr/bin/git config --global --add safe.directory /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/torq
2026-10-07T22:03:32.9982575Z ##[group]Initializing the repository
2026-10-07T22:03:32.9987756Z [command]/usr/bin/git init /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/torq
2026-10-07T22:03:33.0579384Z hint: Using 'master' as the name for the initial branch. This default branch name
2026-10-07T22:03:33.0581124Z hint: will change to "main" in Git 3.0. To configure the initial branch name
2026-10-07T22:03:33.0588024Z hint: to use in all of your new repositories, which will suppress this warning,
2026-10-07T22:03:33.0588878Z hint: call:
2026-10-07T22:03:33.0589186Z hint:
2026-10-07T22:03:33.0589540Z hint: 	git config --global init.defaultBranch <name>
2026-10-07T22:03:33.0589911Z hint:
2026-10-07T22:03:33.0590274Z hint: Names commonly chosen instead of 'master' are 'main', 'trunk' and
2026-10-07T22:03:33.0590819Z hint: 'development'. The just-created branch can be renamed via this command:
2026-10-07T22:03:33.0591410Z hint:
2026-10-07T22:03:33.0591706Z hint: 	git branch -m <name>
2026-10-07T22:03:33.0592035Z hint:
2026-10-07T22:03:33.0592441Z hint: Disable this message with "git config set advice.defaultBranchName false"
2026-10-07T22:03:33.0593174Z Initialized empty Git repository in /home/runner/work/CoChem-TOPOS/CoChem-TOPOS/.cochem-dependencies/torq/.git/
2026-10-07T22:03:33.0594572Z [command]/usr/bin/git remote add origin https://github.com/ProfJJK-CoChem/CoChem-TORQ
2026-10-07T22:03:33.0627631Z ##[endgroup]
2026-10-07T22:03:33.0628040Z ##[group]Disabling automatic garbage collection
2026-10-07T22:03:33.0628560Z [command]/usr/bin/git config --local gc.auto 0
2026-10-07T22:03:33.0667800Z ##[endgroup]
2026-10-07T22:03:33.0668264Z ##[group]Setting up auth
2026-10-07T22:03:33.0672818Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T22:03:33.0721741Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T22:03:33.1001661Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T22:03:33.1050143Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T22:03:33.1301812Z [command]/usr/bin/git config --local http.https://github.com/.extraheader AUTHORIZATION: basic ***
2026-10-07T22:03:33.1344756Z ##[endgroup]
2026-10-07T22:03:33.1351303Z ##[group]Fetching the repository
2026-10-07T22:03:33.1352098Z [command]/usr/bin/git -c protocol.version=2 fetch --no-tags --prune --no-recurse-submodules --depth=1 origin 79fbb111125e50627a1a2c129888a45496f368d4
2026-10-07T22:03:34.0881164Z From https://github.com/ProfJJK-CoChem/CoChem-TORQ
2026-10-07T22:03:34.0881522Z  * branch            79fbb111125e50627a1a2c129888a45496f368d4 -> FETCH_HEAD
2026-10-07T22:03:34.0887612Z ##[endgroup]
2026-10-07T22:03:34.0888234Z ##[group]Determining the checkout info
2026-10-07T22:03:34.0890652Z ##[endgroup]
2026-10-07T22:03:34.0894678Z [command]/usr/bin/git sparse-checkout disable
2026-10-07T22:03:34.0936268Z [command]/usr/bin/git config --local --unset-all extensions.worktreeConfig
2026-10-07T22:03:34.0963311Z ##[group]Checking out the ref
2026-10-07T22:03:34.0966942Z [command]/usr/bin/git checkout --progress --force 79fbb111125e50627a1a2c129888a45496f368d4
2026-10-07T22:03:34.1287776Z Note: switching to '79fbb111125e50627a1a2c129888a45496f368d4'.
2026-10-07T22:03:34.1298728Z 
2026-10-07T22:03:34.1299130Z You are in 'detached HEAD' state. You can look around, make experimental
2026-10-07T22:03:34.1299543Z changes and commit them, and you can discard any commits you make in this
2026-10-07T22:03:34.1299992Z state without impacting any branches by switching back to a branch.
2026-10-07T22:03:34.1300581Z 
2026-10-07T22:03:34.1301093Z If you want to create a new branch to retain commits you create, you may
2026-10-07T22:03:34.1301629Z do so (now or later) by using -c with the switch command. Example:
2026-10-07T22:03:34.1301977Z 
2026-10-07T22:03:34.1302204Z   git switch -c <new-branch-name>
2026-10-07T22:03:34.1302482Z 
2026-10-07T22:03:34.1302695Z Or undo this operation with:
2026-10-07T22:03:34.1302952Z 
2026-10-07T22:03:34.1303154Z   git switch -
2026-10-07T22:03:34.1303376Z 
2026-10-07T22:03:34.1303670Z Turn off this advice by setting config variable advice.detachedHead to false
2026-10-07T22:03:34.1304335Z 
2026-10-07T22:03:34.1304644Z HEAD is now at 79fbb11 Accept exact reviewed TOPOS handoffs into durable TORQ storage
2026-10-07T22:03:34.1305921Z ##[endgroup]
2026-10-07T22:03:34.1338204Z [command]/usr/bin/git log -1 --format=%H
2026-10-07T22:03:34.1360418Z 79fbb111125e50627a1a2c129888a45496f368d4
2026-10-07T22:03:34.1367415Z ##[group]Removing auth
2026-10-07T22:03:34.1370802Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-10-07T22:03:34.1396081Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-10-07T22:03:34.1579697Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-10-07T22:03:34.1599311Z http.https://github.com/.extraheader
2026-10-07T22:03:34.1606031Z [command]/usr/bin/git config --local --unset-all http.https://github.com/.extraheader
2026-10-07T22:03:34.1635392Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-10-07T22:03:34.1812053Z ##[endgroup]
