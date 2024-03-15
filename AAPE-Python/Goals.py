import random
import asyncio
import Sensors
from collections import Counter


class Goal:
    """
    Base class for all actions
    """
    a_agent = None

    def __init__(self, a_agent):
        self.a_agent = a_agent
        self.rc_sensor = a_agent.rc_sensor
        self.i_state = a_agent.i_state

        self.prev_currentActions = []
        self.requested_actions = []

    def requested(self, action):
        """
        Checks if the action is already requested
        :return: number of pending request for that action
        """
        return self.requested_actions.count(action)

    def executing(self, action):
        """
        Checks if the action is already executing
        :return: bool
        """
        if action in self.i_state.currentActions:
            return True
        else:
            return False

    def update_req_actions(self):
        """
        Takes the list i_state.currentActions and finds which actions have been added
        with respect prev_currentActions. Then updates the requested_actions list
        accordingly
        :return:
        """
        counter_prev = Counter(self.prev_currentActions)
        counter = Counter(self.i_state.currentActions)

        # New actions executing that were not executing before
        new_actions_executing = list((counter - counter_prev).elements())
        counter_new_actions = Counter(new_actions_executing)
        counter_req_actions = Counter(self.requested_actions)

        # Remove the new actions from the requested_actions list
        # Remove elements in counter_req_actions that are also in counter_new_actions
        for element, count in counter_new_actions.items():
            counter_req_actions[element] -= min(count, counter_req_actions[element])
        # Reconstruct the modified list counter_req_actions
        modified_req_actions = []
        for element, count in counter_req_actions.items():
            modified_req_actions.extend([element] * count)

        self.requested_actions = modified_req_actions

    async def update(self):
        # update requested actions
        self.update_req_actions()
        self.prev_currentActions = self.i_state.currentActions


class DoNothing(Goal):
    """
    Does nothing
    """
    def __init__(self, a_agent):
        super().__init__(a_agent)

    async def update(self):
        await super().update()
        print("Doing nothing")
        await asyncio.sleep(1)


class ForwardStop(Goal):
    """
    Moves forward till it detects an obstacle and then stops
    """
    STOPPED = 0
    MOVING = 1
    END = 2

    state = STOPPED

    def __init__(self, a_agent):
        super().__init__(a_agent)

    async def update(self):
        await super().update()
        if self.state == self.STOPPED:
            # If we are not moving, start moving
            self.requested_actions.append("W")
            await self.a_agent.send_message("action", "W")
            self.state = self.MOVING
            print("MOVING")
        elif self.state == self.MOVING:
            # If we are moving, check if we detect a wall
            sensor_hit = self.rc_sensor.sensor_rays[Sensors.RayCastSensor.HIT]
            if any(ray_hit == 1 for ray_hit in self.rc_sensor.sensor_rays[Sensors.RayCastSensor.HIT]):
                self.requested_actions.append("S")
                await self.a_agent.send_message("action", "S")
                self.state = self.END
                print("END")
            else:
                await asyncio.sleep(0)
        elif self.state == self.END:
            # If we have finished, don't do anything else
            await asyncio.sleep(10)
            print("WAITING")
        else:
            print("Unknown state: " + str(self.state))


class Turn(Goal):
    """
    Repeats the action of turning a random number of degrees in a random
    direction (right or left) A is left, D is right
    """
    
    def __init__(self, a_agent):
        super().__init__(a_agent)
        
    async def update(self):
        await super().update()
        # Choose a random direction to turn
        turn_direction = random.choice(["A", "D"])
        # Choose a random number of degrees to turn
        turn_degrees = random.randint(-100, 100)
        
        turns_needed = abs(turn_degrees//5) # 5 degrees per turn
        
        print(f"Turning {turn_degrees} degrees to the {turn_direction}, in {abs(turns_needed)} turnsteps.")
        async for _ in self.async_turns(turns_needed):
            self.requested_actions.append(turn_direction)
            await self.a_agent.send_message("action", turn_direction)
            await asyncio.sleep(0.5)
        await asyncio.sleep(10)
        
        
    async def async_turns(self, n):
        for i in range(n):
            yield i
        print("Done turning")



class RandomRoam(Goal):
    """
    Moves around following a direction for a while, changes direction,
    decides to stop, moves again, etc.
    All of this following certain probabilities and maintaining the action during
    a pre-defined amount of time.
    """
    STOPPED = 0
    MOVING = 1
    TURNING = 2
    STOP = 3
    END = 4
    turn_direction = None

    def __init__(self, a_agent):
        super().__init__(a_agent)

    async def update(self):
        await super().update()
        
        if self.state == self.STOPPED:
            # If we are not moving, start moving
            self.requested_actions.append("W")
            await self.a_agent.send_message("action", "W")
            self.state = self.MOVING
            print("MOVING")

        #if it is moving, check if there is any obstacle
        elif self.state == self.MOVING:
            if any(ray_hit == 1 for ray_hit in self.rc_sensor.sensor_rays[Sensors.RayCastSensor.HIT]):
                self.requested_actions.append("S")
                await self.a_agent.send_message("action", "S")
                self.state = self.END
                print("END")
            else:
                await asyncio.sleep(0)
                #choose between stopping, forward, turn
                choice = random.choice([self.TURNING, self.STOPPED, self.MOVING])
                self.state = choice
                print("CHOISING: ", choice)

        elif self.state == self.STOP:
            self.requested_actions.append("S")
            await self.a_agent.send_message("action", "S")
            choice = random.choice([self.TURNING, self.STOPPED, self.MOVING])
            self.state = choice
            print("CHOISING: ", choice)
            
        elif self.state == self.TURNING:
            await asyncio.sleep(0)
            self.turn_direction = random.choice(["A", "D"])
            self.requested_actions.append(self.turn_direction)
            await self.a_agent.send_message("action", self.turn_direction)
            await asyncio.sleep(2)
            
            choice = random.choice([self.TURNING, self.STOPPED, self.MOVING])
            self.state = choice
            print("CHOISING: ", choice)

        
        elif self.state == self.END:
            # If we have finished, don't do anything else
            await asyncio.sleep(10)
            print("WAITING")

        else:
            print("Unknown state: " + str(self.state))


class Avoid(Goal):
    """
    Moves always forward avoiding obstacles
    """
    STOPPED = 0
    MOVING = 1
    DECIDING = 2
    TURNING = 3
    AVOIDING_OBSTACLE = 4
    ALIGNING = 5
    END = 6
    state = STOPPED
    turn_direction = None
    avoid_distance = 0
    align_distance = 0

    def __init__(self, a_agent):
        super().__init__(a_agent)

    async def update(self):
        await super().update()
        
        if self.state == self.STOPPED:
            # If we are not moving, start moving
            self.requested_actions.append("W")
            await self.a_agent.send_message("action", "W")
            self.state = self.MOVING
            print("MOVING")

        #if it is moving, check if there is any obstacle
        elif self.state == self.MOVING:
        
            if all(ray_hit == 1 for ray_hit in self.rc_sensor.sensor_rays[Sensors.RayCastSensor.HIT]):
                self.requested_actions.append("S")
                await self.a_agent.send_message("action", "S")
                self.state = self.END
                print("END")

            if any(ray_hit == 1 for ray_hit in self.rc_sensor.sensor_rays[Sensors.RayCastSensor.HIT]):
                self.requested_actions.append("S")
                await self.a_agent.send_message("action", "S")

                self.state = self.DECIDING
                print("DECIDING")

            else:
                await asyncio.sleep(0)
        
        elif self.state == self.DECIDING:

            center_index = len(self.rc_sensor.sensor_rays[Sensors.RayCastSensor.HIT]) // 2

            # Check if only the center sensor detects an obstacle
            if self.rc_sensor.sensor_rays[Sensors.RayCastSensor.HIT][center_index] == 1 and \
            all(ray_hit == 0 for i, ray_hit in enumerate(self.rc_sensor.sensor_rays[Sensors.RayCastSensor.HIT]) if i != center_index):
                # Choose randomly between left ("A") and right ("D") if the center sensor detects something
                self.turn_direction = random.choice(["A", "D"])
                self.avoid_distance = 0 
                self.state = self.TURNING
                print(f"TURNING: {self.turn_direction}")

            else:
                left_hits = sum(self.rc_sensor.sensor_rays[Sensors.RayCastSensor.HIT][:center_index])  # Consider left without the center
                right_hits = sum(self.rc_sensor.sensor_rays[Sensors.RayCastSensor.HIT][center_index + 1:])  # Consider right without the center
                self.turn_direction = "A" if left_hits > right_hits else "D"
                self.avoid_distance = 0 
                self.state = self.TURNING
                print(f"TURNING: {self.turn_direction}")
        
        elif self.state == self.TURNING:
            # Turn a little bit to avoid the obstacle
            self.requested_actions.append(self.turn_direction)
            await self.a_agent.send_message("action", self.turn_direction)
            await asyncio.sleep(2)
            self.state = self.AVOIDING_OBSTACLE
            print("AVOIDING")
        
        elif self.state == self.AVOIDING_OBSTACLE:
            # Move forward a bit to pass the obstacle
            if self.avoid_distance < 10:  # This is an arbitrary distance; adjust based on your simulation
                self.requested_actions.append("W")
                await self.a_agent.send_message("action", "W")
                self.avoid_distance += 1
            else:
                self.avoid_distance = 0  # Reset avoid_distance for potential future use
                self.align_distance = 0  # Initialize align_distance for the ALIGNING phase
                self.state = self.ALIGNING
                print("ALIGNING")

        elif self.state == self.ALIGNING:
            # Align back to the original direction
            if self.align_distance < 5:  # This is an arbitrary distance; adjust based on your simulation
                opposite_direction = "A" if self.turn_direction == "D" else "D"
                self.requested_actions.append(opposite_direction)
                await self.a_agent.send_message("action", opposite_direction)
                self.align_distance += 1
            else:
                self.state = self.MOVING  # Change state back to MOVING to continue forward movement
                print("MOVING FORWARD")
        
        elif self.state == self.END:
            # If we have finished, don't do anything else
            await asyncio.sleep(10)
            print("WAITING")

        else:
            print("Unknown state: " + str(self.state))

