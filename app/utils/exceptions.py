class BaseAppException(Exception):
    def __init__(self, message="An error occurred", status_code=500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)

class APIConnectionError(BaseAppException):
    def __init__(self, service_name, original_error=None):
        message = f"Failed to connect to {service_name} service"
        if original_error:
            message += f": {str(original_error)}"
        super().__init__(message, status_code=503)

class TranscriptionError(BaseAppException):
    def __init__(self, original_error=None):
        message = "Failed to transcribe audio"
        if original_error:
            message += f": {str(original_error)}"
        super().__init__(message, status_code=500)

class SynthesisError(BaseAppException):
    def __init__(self, original_error=None):
        message = "Failed to synthesize speech"
        if original_error:
            message += f": {str(original_error)}"
        super().__init__(message, status_code=500)

class SlotFillingError(BaseAppException):
    def __init__(self, original_error=None):
        message = "Failed to extract information from user input"
        if original_error:
            message += f": {str(original_error)}"
        super().__init__(message, status_code=500)
