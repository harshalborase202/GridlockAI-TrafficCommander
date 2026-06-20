# frame_extractor.py
# Manages in-memory rolling frame buffer and schedules dynamic extraction tasks for pre/post-violation frames.

class FrameExtractor:
    def __init__(self, fps):
        """
        Initialize FrameExtractor.
        Args:
            fps: Video frames per second.
        """
        self.fps = fps
        self.buffer_size = 2 * fps  # Storing up to 2 seconds of historical frames
        self.frame_buffer = []  # Ring buffer list of tuples: (frame_idx, frame_img)
        self.active_tasks = {}  # Active collection tasks: {violation_id: task_details_dict}

    def add_frame(self, frame_idx, frame_img):
        """
        Add the current frame to the in-memory ring buffer.
        """
        self.frame_buffer.append((frame_idx, frame_img.copy()))
        if len(self.frame_buffer) > self.buffer_size + 1:
            self.frame_buffer.pop(0)

    def start_extraction_task(self, violation_id, violation_frame_idx, bbox):
        """
        Initialize a frame extraction task for a specific violation.
        Pulls past frames from the buffer immediately.
        """
        # Determine exact frames to extract
        f_minus2 = violation_frame_idx - (2 * self.fps)
        f_minus1 = violation_frame_idx - self.fps
        f_0 = violation_frame_idx

        # Retrieve frames from buffer with fallback to oldest available frame if index is out of bounds
        img_minus2 = self._get_frame_from_buffer(f_minus2)
        img_minus1 = self._get_frame_from_buffer(f_minus1)
        img_0 = self._get_frame_from_buffer(f_0)

        # Initialize the task dictionary
        self.active_tasks[violation_id] = {
            "violation_id": violation_id,
            "violation_frame": violation_frame_idx,
            "bbox": bbox,
            "frames": {
                "frame_minus2": img_minus2,
                "frame_minus1": img_minus1,
                "frame_0": img_0,
                "frame_plus1": None,
                "frame_plus2": None
            }
        }

    def update_tasks(self, current_frame_idx, current_frame_img):
        """
        Scan active tasks and append current frame if it aligns with T+1s or T+2s.
        Returns a list of completed task dicts.
        """
        completed_tasks = []
        finished_ids = []

        for v_id, task in self.active_tasks.items():
            violation_frame = task["violation_frame"]
            
            # Check T + 1 second
            if current_frame_idx == violation_frame + self.fps:
                task["frames"]["frame_plus1"] = current_frame_img.copy()
                
            # Check T + 2 seconds (task completes)
            elif current_frame_idx == violation_frame + (2 * self.fps):
                task["frames"]["frame_plus2"] = current_frame_img.copy()
                completed_tasks.append(task)
                finished_ids.append(v_id)

        # Clear finished tasks from active monitoring
        for v_id in finished_ids:
            del self.active_tasks[v_id]

        return completed_tasks

    def _get_frame_from_buffer(self, target_idx):
        """Helper to find frame by index or fallback to the closest match."""
        if not self.frame_buffer:
            return None

        # Search for exact match
        for idx, img in self.frame_buffer:
            if idx == target_idx:
                return img.copy()

        # Fallback 1: Return the first frame in buffer if target is older (e.g. at the video start)
        if target_idx < self.frame_buffer[0][0]:
            return self.frame_buffer[0][1].copy()

        # Fallback 2: Return the latest frame in buffer if target is newer
        return self.frame_buffer[-1][1].copy()
