
# LaserJoints

Laserjoints is an inkscape extension that helps preparing 3D assemblies from 2D shapes for laser cutting.

# Basic usage workflow : 
1. prepare 2D shapes
2. **convert shapes to path**
3. create flags using the "create flags" option: male, female or slots
4. position the flags on the relevant edges
5. adjust flag parameters, thickness and kerf
6. run "Joints/Create Joints"
7. a new layer is created containing the prepared shapes.

## Demos
### Simple demo:

<img width="758" height="312" alt="laserjoints_demo_1" src="https://github.com/user-attachments/assets/632684ac-aa67-4181-b546-a49fdbadf088" />

### Walls and curves:
<img width="1222" height="714" alt="laserjoints_short_demo" src="https://github.com/user-attachments/assets/4c79b569-e26c-4347-920f-03b69b08341b" />

### short tuto
[laserjoints_long_demo.webm](https://github.com/user-attachments/assets/524acbc6-7aa3-4617-91d9-55ff93c6c011)

## Installation

Run Inkscape and go to `Edit > Preferences > System` and check the `User extensions` folder.
Copy the two files, `laserjoints.inx` and `laserjoints.py` into that folder, and restart Inkscape.

# Features : 
- create joints by manually positioning flags.
- create joints by automatically positioning flags : flags pairs (M/F) will be set on segments that have the same length.
- choose joints side : inside / outside by adjusting flag position
- curves support
- walls generation : to create an "E" letter in 3D, use the "create walls" option.
- curved walls support : combine with the Living Hinge extension (https://github.com/buxtronix/living-hinge)

# Known bugs/caveats :
- an unused "square" is kept in the corner : it will be cut by the laser and should not be an issue in most cases.

## 💖 Support the Project
This extension has been developped and tested at our local [Lou Fabiloub](https://loufabiloub.fr) makerspace in Avignon.
I've built it on my (precious) spare time, so if you find this project helpful, please consider supporting its ongoing development and maintenance:

[![Sponsor me on GitHub](https://shields.io)](https://github.com)

Every contribution—whether it's a one-time donation, a monthly sponsorship, or simply starring the repo—helps keep this project alive and well-maintained. Thank you!


## Connected/Similar/Inspiring projects

* https://github.com/JarrettR/QuickJoint
* https://github.com/florianfesti/boxes
* https://github.com/buxtronix/living-hinge
