# AX4U Traffic Accident Video Analyzer Specification

## Goal

AX4U is an evidence-assistance tool for traffic accident video analysis. It calculates speed, perception distance, braking distance, stopping distance, avoidance geometry, and avoidability from user-marked video frames and user-entered real-world distances.

The program must not invent a speed from screen pixel distance alone. Speed is calculated only when a usable real distance and elapsed frame time are available.

## Core Formulae

Elapsed time:

```text
time_s = (end_frame - start_frame) / fps
```

Speed:

```text
speed_kmh = distance_m / time_s * 3.6
```

Perception distance:

```text
perception_distance_m = speed_mps * user_reaction_time_s
```

Braking deceleration:

```text
a = friction_coefficient * 9.80665
```

Braking distance:

```text
braking_distance_m = speed_mps^2 / (2 * a)
```

Stopping distance:

```text
stopping_distance_m = perception_distance_m + braking_distance_m
```

Collision residual speed with available distance:

```text
braking_available_distance = max(0, available_distance_m - perception_distance_m)
v_collision^2 = max(0, v_initial^2 - 2 * a * braking_available_distance)
```

Avoidance angle:

```text
angle_deg = atan2(lateral_distance_m, longitudinal_distance_m)
```

## Data Model

Marked video point:

- marker type
- frame index
- time seconds
- timecode
- image x
- image y

Distance measurement result:

- distance_m
- distance_method
- calibration_value
- confidence
- warning

Calculation result:

- vehicle name
- measurement start frame
- measurement end frame
- contact frame
- measurement time
- actual movement distance
- distance method
- speed at perception point
- direct contact speed
- calculated contact speed
- reaction time
- perception distance
- braking distance
- stopping distance
- available distance
- residual collision speed
- avoidance distance
- lateral distance
- avoidance angle
- avoidability
- warnings
- calculation basis

## Validation Rules

- FPS must be greater than zero.
- End frame must be greater than start frame for speed measurement.
- A zero frame difference is an invalid speed interval, not a crash condition.
- Real movement distance must be positive to calculate direct speed.
- Missing values produce explicit warnings instead of program termination.
- Extremely high values are displayed with warnings, not hidden or replaced.
- Perception frame and braking frame may be identical.
- User reaction time and video frame interval are separate values.

