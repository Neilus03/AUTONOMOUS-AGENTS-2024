import sys
import aiohttp
import asyncio
import json
import Sensors
import Goals


class InternalState:
    """
    Internal state
        Stores the internal state of the agent.
            currentActions: list<string> Actions the agent is currently executing
                           [W | D | A | S | Z]
            speed: <float> Speed of the agent
            position: <dict { "x": <float>, "y": <float>, "z": <float> } Position using world coordinates
            rotation: <dict { "x": <float>, "y": <float>, "z": <float> } Rotation y - Yaw, x - Pitch, z - Roll
    """
    def __init__(self):
        self.currentActions = []
        self.speed = 0.0
        self.position = {"x": 0, "y": 0, "z": 0}
        self.rotation = {"x": 0, "y": 0, "z": 0}

    def set_internal_state(self, i_state_dict):
        self.currentActions = i_state_dict["currentActions"]
        self.speed = i_state_dict["speed"]
        self.position = i_state_dict["position"]
        self.rotation = i_state_dict["rotation"]


class AAgent:
    # Constants that define the state of the simulation
    ON_HOLD = 0
    RUNNING = 1

    def __init__(self, config_file_path: str):
        # Read the agent configuration file and put the info in the 'config' dictionary.
        with open(config_file_path, 'r') as file:
            config_data = file.read()
            self.config = json.loads(config_data)
        # Extract the parameters of the agent from the config dictionary
        self.AgentParameters = self.config['AgentParameters']

        # URL to connect with Unity
        self.url = f"ws://{self.config['Server']['host']}:{self.config['Server']['port']}/"

        # Agent sensors
        self.rc_sensor = Sensors.RayCastSensor(self.AgentParameters['ray_perception_sensor_param'])

        # Agent internal state
        self.i_state = InternalState()

        # Misc. variables
        # variables used for the websocket connection
        self.session = None
        self.ws = None
        # State of the simulation: ON_HOLD | RUNNING
        self.simulation_state = self.ON_HOLD
        # Asyncio exit event used to notify the tasks that they have to finish
        self.exit_event = asyncio.Event()
        # Flag that confirms the connection with Unity is fully operative and that Unity is waiting for messages
        self.connection_ready = False

        # Reference to the possible goals the agent can execute
        self.goals = {
            "DoNothing": Goals.DoNothing(self),
            "ForwardStop": Goals.ForwardStop(self),
            "Turn": Goals.Turn(self),
            "RandomRoam": Goals.RandomRoam(self),
            "Avoid": Goals.Avoid(self)
        }
        # Active goal
        self.currentGoal = "DoNothing"

    async def open_websocket(self):
        """
        Establishes the connection with Unity using a websocket. After that, it sends the initial parameters of the
        agent, obtained previously from the configuration file.
        """
        try:
            self.session = aiohttp.ClientSession()
            print("Connecting to: " + self.url)
            self.ws = await self.session.ws_connect(self.url)
            print("Connected to WebSocket server")
            param_json = json.dumps(self.AgentParameters)
            print("Sending the initial parameters: " + param_json)
            await self.send_message("initial_params", param_json)
        except:
            print("Failed connection")
            self.exit_event.set()

    async def close_websocket(self):
        """
        Properly close the websocket connection.
        """
        if self.ws:
            await self.ws.close()
        if self.session:
            await self.session.close()
        print("WebSocket connection properly closed")

    async def send_message(self, msg_type: str, msg_content: str):
        """
        Sends a message in json format of type 'msg_type' and with content 'msg_content' to Unity
        :param msg_type: General type of the message.
        :param msg_content: Content of the message
        """
        msg = {"type": msg_type, "content": msg_content}
        msg_json = json.dumps(msg)
        await self.ws.send_str(msg_json)

    async def receive_messages(self):
        """
        Gets the messages that arrive from Unity through the websocket. If the message is not a 'close' message or
        an error, it calls the function 'process_incoming_message() to process it.
        """
        try:
            # With this loop, we will repeatedly await the next value produced by iterating over self.ws.
            # At each iteration, the event loop will suspend execution until a new value becomes available
            # from self.ws. The loop continues iterating over self.ws till the websocket is closed.
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self.process_incoming_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    print("Connection closed by Unity")
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    print(f"WebSocket connection closed with error: {self.ws.exception()}")
                    break
        except Exception as e:
            print(f"Connection failed: {e}")
        finally:
            print("Finishing receive_messages")
            self.exit_event.set()

    def process_incoming_message(self, msg_data: str):
        """
        Processes the message 'msg_data' received from Unity. It is expected to be in json format.
        :param msg_data: Message received in json format.
        """
        try:
            msg_dict = json.loads(msg_data)

            if msg_dict["Type"] == "sensor":
                self.rc_sensor.set_perception(msg_dict["Content"][0])
                self.i_state.set_internal_state(msg_dict["Content"][1])
            elif msg_dict["Type"] == "sim_control":
                if msg_dict["Content"] == "connection_ready":
                    self.connection_ready = True
                elif msg_dict["Content"] == "on_hold":
                    self.simulation_state = self.ON_HOLD
                    print("ON HOLD")
                elif msg_dict["Content"] == "start":
                    self.simulation_state = self.RUNNING
                    print("RUNNING")
                elif msg_dict["Content"] == "error":
                    print("Error creating the agent in Unity.")
                    self.exit_event.set()
                else:
                    print("Received unknown message - Type: " + msg_dict["Type"] + "- Content: " + msg_dict["Content"])
            elif msg_dict["Type"] == "agent_control":
                # These kind of messages have the format
                # command:data
                try:
                    command, data = msg_dict["Content"].split(":")
                    if command == "goal":
                        self.currentGoal = data
                    else:
                        print("Agent_control message with an unknown command: " + msg_dict["content"])
                except Exception as e:
                    print(f"Exception: {e}")
            else:
                print("Received unknown message - Type: " + msg_dict["Type"] + "- Content: " + msg_dict["Content"])
        except json.JSONDecodeError as e:
            print(f"Failed JSON decoding of the received message: {msg_data}")
        except Exception as e:
            print(f"Exception: {e}")
            raise e

    async def main_loop(self):
        # Keep going while there is not an event to exit
        while not self.exit_event.is_set():
            # Control if we are on hold (simulation paused from Unity)
            if self.simulation_state == self.ON_HOLD:
                # Just wait, but allow the other tasks keep running
                await asyncio.sleep(0)
            else:
                # Here is where we perform the agent actions calling the update() method
                # of the corresponding active goal
                try:
                    await self.goals[self.currentGoal].update()
                except Exception as e:
                    # In case there is an error executing the update() of the goal,
                    # instead of finishing we change the goal to DoNothing
                    print("Execution of goal " + self.currentGoal + " failed.")
                    print(f"Exception: {e}")
                    self.currentGoal = "DoNothing"
        print("Finishing main_loop")

    async def run(self):
        try:
            # Create the connection task, that will manage the connection with Unity,
            # and the exit_event task, that will be used to exit if there is an error
            connect_task = asyncio.create_task(self.open_websocket())
            awaited_exit_event = asyncio.create_task(self.exit_event.wait())

            # Wait for the connection with Unity to be ready or the exit event, what comes first
            await asyncio.wait([connect_task, awaited_exit_event], return_when=asyncio.FIRST_COMPLETED)

            if not self.exit_event.is_set():
                # Now that the connection is established, create the task to start receiving messages from Unity
                # We are not awaiting this task because it has to run forever till the main loop finishes
                asyncio.create_task(self.receive_messages())
                # Wait for the flag "connection_ready" to be True. If it is true, it means we have received an ack
                # from Unity saying that the connection is fully established and Unity is ready to receive messages
                while not self.connection_ready:
                    await asyncio.sleep(0)
                print("Connection with Unity fully established")
                # We are ready now  to start the main loop of the agent
                await self.main_loop()
        finally:
            # Notify other possible running tasks that we have to exit
            self.exit_event.set()
            # Clean the websocket connection
            await self.close_websocket()
            print("Connection with Unity closed")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python AAgent_Python.py <init_file.json>")
    else:
        # Get the name of the file with the initial parameters
        init_file = sys.argv[1]

        # Creates an instance of the AAgent_Python class.
        my_AAgent = AAgent(init_file)

        # Run the AAgent. It creates a new event loop, runs the my_AAgent.run()
        # coroutine in that event loop, and then closes the event loop when the coroutine completes.
        asyncio.run(my_AAgent.run())

        print("Bye!!!")
