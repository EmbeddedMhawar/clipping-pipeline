# 0007: Workspace-Level Channel Portfolio Registry

To support multi-channel warmup lifecycles and posting cadences across dozens of video clipping projects, channel identities and warmup states are stored in a dedicated workspace-level `channels.json` registry rather than inside project-level `.clipping_state.json` files. Video clipping runs query this registry during execution and update its post logs without coupling single-video timeline state to persistent account lifecycles.
