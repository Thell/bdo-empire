# bdo-empire

## About

Given a contribution point limit and price list this program will find the
optimum allocation of the points to maximize a Worker Node Empire's value.

It
  - generates a json file to import into [Workerman][workerman]
  - uses workers of level 40 with average stats.
  - uses workers with optimum skills learned.
  - assumes all drops are sent to storage with zero cost (Calpheon).

and, when specified, it
  - accounts for p2w bonus lodging.
  - accounts for workshop reserved _lodging cost_ but not profits or the workshop itself.
  - accounts for forced taken node connections for Grinding.
  - optimizes _lodging cost_ for Farming Fence workers into any available town  
    (by selecting fences in the force taken list).
  - extends _lodging and worker nodes_ from a base empire exported from Workerman.

It does not
  - account for CP spent outside of the Node Empire.

This program uses the HiGHS High Performance Optimization Software to solve
the MIP using branch and cut. The parameters chosen guarantee the result is
within 0.01% of the optimum value but in practice it is optimum for all test
cases used during the development and testing of the model. If exact results
are desired the `main.py` source can be edited such that `optimize_config`
`top_n`, `nearest_n` are increased to at least `10`, `10` respectively but do
this with caution because the runtime can and will increase to multiple hours.

**NOTE:**  Every change in input or options can alter the runtime! There is no
real average but empirically budgets of ~350 or ~600 take the longest and all
of the bench cases for v0.7.0 completed in < 1h15m when testing every
increment of 25 from 50 to 625. The vast majority of those completed nearer to
20 minutes or less. Good luck, be patient, and if needed use the 'stop'
button to use the best solution found so far which is usually the resulting
optimal solution if you let it run for ~30 minutes.


## Installation

Using pipx: `pipx install bdo-empire`  
Using pip: `pip install bdo-empire`

## Updating to latest version

Using pipx: `pipx upgrade bdo-empire`  
Using pip: `pip install bdo-empire -U`

## Usage

**Requirements**
  - python >= 3.12
  - an exported price list* from [Workerman settings page][settings].
  - optional; an exported modifiers list from [Workerman modifiers page][modifiers]
    (click `▶Advanced`).
  - optional; an exported 'base' empire from the [Workerman][workerman] page.

\* Use the 'reload' button on workerman's setting page prior to exporting.

**Start the program**

Installed using pipx: `empire-optimizer.exe`  
Installed using pip: `python -m bdo_empire.main`


Fill in the required fields, click **Optimize** and then wait.


[workerman]:https://shrddr.github.io/workerman
[settings]:https://shrddr.github.io/workerman/settings
[modifiers]:https://shrddr.github.io/workerman/modifiers
[release]:https://github.com/thell/bdo-empire/releases/latest
