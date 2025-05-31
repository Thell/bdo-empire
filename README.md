# bdo-empire

## About

Given a contribution point limit and price list this program will find the
optimum allocation of the points to maximize a Worker Node Empire's value.

It
  - generates a json file to import into [Workerman][workerman]
  - uses workers of level 40.
  - uses workers with optimum skills learned.
  - assumes all drops are sent to storage with zero cp cost (Calpheon).
  - accounts for workshop _lodging cost_ but not profits or the workshop itself.
  - accounts for grinding node connections

It does not
  - account for cp spent outside of the Node Empire.

This program uses the HiGHS High Performance Optimization Software to solve
the MIP using branch and cut. The parameters chosen guarantee the result is
within 0.01% of the optimum value but in practice it is optimum for all test
cases used during the development and testing of the model.

## Installation

Using pipx: `pipx install bdo-empire`  
Using pip: `pip install bdo-empire`

## Usage

**Requirements**
  - python
  - an exported price list* from [Workerman settings page][settings].
  - optionally; an exported modifiers list from [Workerman modifiers page][modifiers]
    (click `▶Advanced`).

\* Use the 'reload' button on workerman's setting page prior to exporting.

**Start the program**

Installed using pipx: `empire-optimizer.exe`  
Installed using pip: `python -m bdo_empire.main`


Fill in the required fields, click **Optimize** and then wait.

All test instances using a variety of input parameters solved in under an hour
but each combination of CP, pricing, purchased lodging and region modifiers
will alter solution time.


[workerman]:https://shrddr.github.io/workerman
[settings]:https://shrddr.github.io/workerman/settings
[modifiers]:https://shrddr.github.io/workerman/modifiers
[release]:https://github.com/thell/bdo-empire/releases/latest
