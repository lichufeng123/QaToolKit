import java.nio.file.Files
import java.nio.file.Paths
import java.nio.file.StandardOpenOption

def logDir = "E:/性能测试/jmeter_logs/Image"
def logPath = logDir + "/final_Image_result.csv"

Files.createDirectories(Paths.get(logDir))

String status = vars.get("currentTaskStatus")
int count = vars.get("pollCount") as int
int maxCount = vars.get("maxPollCount") as int


String result = "FAILED"
String message = ""


if (status == "SUCCESS" ) {
    result = "SUCCESS"
    SampleResult.setSuccessful(true)
    SampleResult.setResponseMessage(
        "出图成功，最后status=" + status
        + ", 轮询次数=" + count
    )
    
} else if (count >= maxCount) {
    result = "TIMEOUT"
    SampleResult.setSuccessful(false)
    SampleResult.setResponseMessage(
        "出图超时，getResult 未返回有效图片"
        + ", 最后status=" + status
        + ", 轮询次数=" + count
    )
} else {
    result = "FAILED"
    SampleResult.setSuccessful(false)
    SampleResult.setResponseMessage(
        "出图失败"
        + ", 最后status=" + status
    )
}

def line = "${result},${count},${status}\n"

synchronized(this.getClass()) {
    Files.write(
        Paths.get(logPath),
        line.getBytes("UTF-8"),
        StandardOpenOption.CREATE,
        StandardOpenOption.APPEND
    )
}