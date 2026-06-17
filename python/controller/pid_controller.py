

class PIDController:
    def __init__(self, kp, ki, kd, dt, output_limits=(-1, 1)):
        """
        Parameters:
        kp, ki, kd: PID gains
        dt: time step between two samples (seconds)
        output_limits: min/max output limits (e.g., steering angle between -1 and 1)
        """
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.dt = dt
        self.limit_min, self.limit_max = output_limits

        # Internal state variables
        self._integral = 0.0
        self._prev_error = 0.0
        self._prev_output = 0.0

    def update(self, error):
        """
        Args:
            error: current error value (e.g., target_angle - current_angle)
        Returns:
            Steering command after applying output limits
        """
        # Proportional term
        p = self.kp * error

        # Integral term (with simple anti-windup)
        self._integral += error * self.dt
        i = self.ki * self._integral

        # Derivative term (using error change over time)
        derivative = (error - self._prev_error) / self.dt if self.dt > 0 else 0.0
        d = self.kd * derivative

        # Raw output before clamping
        output = p + i + d

        # Clamp the output to the allowed range
        if output > self.limit_max:
            output = self.limit_max
            # Optional anti-windup: uncomment the next line to stop integrating when saturated
            # self._integral -= error * self.dt
        elif output < self.limit_min:
            output = self.limit_min
            # self._integral -= error * self.dt

        # Store current error for the next derivative calculation
        self._prev_error = error
        self._prev_output = output
        return output

    def reset(self):
        """Reset the internal state (integral and previous error) for a fresh start"""
        self._integral = 0.0
        self._prev_error = 0.0
        self._prev_output = 0.0
