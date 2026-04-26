flowchart TD
  %% =====================
  %% IMAGE PIPELINE (A): RealSense -> ZMQ -> Worker -> Disk
  %% =====================

  subgraph RS["real/teleop/image_server/ (Robot PC)"]
    RS_S["realsense_server.py\n- imports: pyrealsense2, cv2, zmq, numpy\n- Captura frames RealSense\n- Encode: RGB/IR JPG, Depth raw uint16 bytes\n- Devuelve por ZMQ REP: [rgb_jpg_bytes, ir_jpg_bytes, depth_bytes]\n- NO guarda a disco"]
  end

  subgraph HOST["real/teleop/ (Host)"]
    MAIN["main.py\n- crea TeleopManager\n- start_processes + REPL (s/q/d/exit)"]

    MGR["manager.py (TeleopManager)\n- imports: RobotTaskmaster, RobotDataWorker\n- crea shared_memory + shared_dict\n- update_directory(): crea dirs\n  <dirname>/color\n  <dirname>/depth\n- start_session(): set session_start_event\n- stop_session(): set kill_event"]

    MASTER["master_whole_body.py (RobotTaskmaster)\n- lee robot DDS (body+hands)\n- lee teleop VR (PICO)\n- calcula torso_height + torso_rpy (solve_lower_ik)\n- captura vx, vy, vyaw (sticks)\n- integra target_yaw\n- llama solve_whole_body_ik() -> pd_target (lower+arm)\n- aplica a robot\n- escribe ik_data.jsonl via IKDataWriter.write_data()\n- devuelve/log actions: right_qpos,left_qpos, torso_rpy,h_b,vx,vy,vyaw,dyaw,target_yaw"]

    VR["vr_pico.py (PicoTeleop)\n- imports: PicoReceiver + VuerPreprocessor\n- step() devuelve:\n  head_rmat,\n  left_wrist_mat,\n  right_wrist_mat,\n  left_hand_q,\n  right_hand_q"]

    IK["robot_control/robot_body_ik.py (G1_29_BodyIK)\n- solve_lower_ik() -> (h_new, rpy_new)\n- solve_whole_body_ik() -> (pd_target, pd_tauff, raw_action)\n  - lower body (15) sale del policy_jit\n  - arm (14) se rellena con solve_arm_ik en teleop"]

    WORKER["worker.py (RobotDataWorker)\n- imports: zmq, cv2, numpy, lzma\n- _recv_zmq_frame(): pide ZMQ, recibe [rgb_jpg, ir_jpg, depth_bytes]\n  devuelve: rgb_array(uint8 bytes), ir_array(uint8 bytes), depth_array(uint16 480x640)\n- _write_image_data():\n  guarda <dirname>/color/frame_XXXXXX.jpg\n  guarda <dirname>/depth/frame_XXXXXX.npy.lzma\n- get_robot_data(): escribe paths relativos en JSON\n  image: color/frame_XXXXXX.jpg\n  depth: depth/frame_XXXXXX.npy.lzma\n- escribe robot_data.jsonl"]

    WRT["writers.py\n- AsyncImageWriter: decodifica jpg bytes -> cv2.imwrite\n- AsyncWriter: append json lines\n- IKDataWriter: escribe ik_data.jsonl (torso_rpy,h_b,vx,vy,vyaw,target_yaw, hand qpos, etc.)"]

    MERGE["merger.py (DataMerger)\n- lee robot_data.jsonl + ik_data.jsonl\n- alinea por tiempo (armtime vs time)\n- escribe <dirname>/data.json"]
  end

  %% Connections: start-up
  MAIN --> MGR
  MGR -->|spawn process| MASTER
  MGR -->|spawn process| WORKER

  %% Teleop + IK + logging
  MASTER --> VR
  MASTER --> IK
  MASTER --> WRT

  %% ZMQ image fetch + saving
  WORKER -->|ZMQ REQ get_frame| RS_S
  RS_S -->|multipart reply| WORKER
  WORKER --> WRT

  %% Output dataset artifacts
  WORKER -->|writes| DISK1["<dirname>/color/frame_*.jpg\n(vía writers.AsyncImageWriter)"]
  WORKER -->|writes| DISK2["<dirname>/depth/frame_*.npy.lzma\n(vía worker.depth_writer_process)"]
  WORKER -->|writes| DISK3["<dirname>/robot_data.jsonl"]
  MASTER -->|writes| DISK4["<dirname>/ik_data.jsonl"]
  MASTER --> MERGE
  WORKER --> MERGE
  MERGE -->|writes| DISK5["<dirname>/data.json (merged)"]

  %% =====================
  %% EPISODE PIPELINE (B): EpisodeWriter (separate)
  %% =====================
  subgraph EP["real/teleop/utils/ (Alternate episode format)"]
    EW["episode_writer.py (EpisodeWriter)\n- create_episode(): crea episode_XXXX/{colors,depths,audios}/\n- add_item(colors, depths, ...)\n- _process_item_data(): cv2.imwrite\n- _save_episode(): escribe episode_XXXX/data.json"]
  end

  EW -->|writes| EDISK["<task_dir>/episode_XXXX/colors/*.jpg\n<task_dir>/episode_XXXX/depths/*.jpg\n<task_dir>/episode_XXXX/data.json"]
