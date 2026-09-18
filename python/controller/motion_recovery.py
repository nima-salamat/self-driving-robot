class MotionRecoveryPlanner:
    """
    Future recovery module placeholder.

    Do not put route-deviation detection, PID logic, or motor commands in
    MotionHistory. This module is the intended place for the future coordinator.

    Planned responsibilities:
      - consume MotionHistory.timeline(),
      - receive a perception/trajectory deviation signal,
      - identify the latest safe recovery boundary,
      - reject unsafe/incomplete history,
      - generate a bounded replay plan,
      - hand the plan to RobotController for execution.

    The planner must never blindly replay all 200 pulses.
    """

    def __init__(self, history):
        self.history = history

    def plan(self, deviation, *, safe_boundary=None):
        raise NotImplementedError(
            "Route-deviation recovery is intentionally not implemented yet."
        )
