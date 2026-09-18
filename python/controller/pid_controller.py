import time


class PIDController:
    def __init__(
        self,
        kp,
        ki,
        kd,
        dt=0.01,
        output_limits=(-1, 1),
        min_dt=0.001,
        max_dt=0.2,
        derivative_filter=0.25,
    ):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.dt = dt
        self.limit_min, self.limit_max = output_limits
        self.min_dt = max(1e-6, float(min_dt))
        self.max_dt = max(self.min_dt, float(max_dt))
        self.derivative_filter = max(0.0, min(1.0, float(derivative_filter)))

        self._integral = 0.0
        self._prev_error = None
        self._prev_derivative = 0.0
        self._prev_output = 0.0
        self._last_time = None

    def update(self, error, now=None):
        now = time.monotonic() if now is None else float(now)

        if self._last_time is None:
            dt = self.dt if self.dt > 0 else 0.01
        else:
            dt = now - self._last_time

        self._last_time = now
        if not dt > 0:
            dt = self.min_dt
        dt = min(max(dt, self.min_dt), self.max_dt)

        if self._prev_error is None:
            derivative = 0.0
        else:
            raw_derivative = (error - self._prev_error) / dt
            alpha = self.derivative_filter
            derivative = (
                alpha * raw_derivative
                + (1.0 - alpha) * self._prev_derivative
            )

        p = self.kp * error

        if self.ki != 0.0:
            candidate_integral = self._integral + error * dt
            candidate_i = self.ki * candidate_integral
        else:
            candidate_integral = self._integral
            candidate_i = 0.0

        d = self.kd * derivative
        unclamped = p + candidate_i + d
        output = min(self.limit_max, max(self.limit_min, unclamped))

        # Conditional integration prevents further windup while saturated
        # in the same direction as the error.
        if self.ki != 0.0:
            saturated_high = output >= self.limit_max and error > 0
            saturated_low = output <= self.limit_min and error < 0
            if not (saturated_high or saturated_low):
                self._integral = candidate_integral

        self._prev_error = error
        self._prev_derivative = derivative
        self._prev_output = output
        return output

    def reset(self):
        self._integral = 0.0
        self._prev_error = None
        self._prev_derivative = 0.0
        self._prev_output = 0.0
        self._last_time = None
