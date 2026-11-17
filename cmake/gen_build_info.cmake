# 生成构建身份头文件（build/build_info.h）：git 短哈希(-dirty) + 本地时间戳。
# 内容没变就不覆写——ninja 每次构建都会跑本目标，幂等写避免无谓重编译 main.c。
# 由 CMakeLists.txt 的 build_info 目标传入 OUT / GIT_EXEC / SRC_DIR。

set(_id "unknown")
if(GIT_EXEC)
    execute_process(
        COMMAND ${GIT_EXEC} -C ${SRC_DIR} describe --always --dirty
        OUTPUT_VARIABLE _id
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET
        RESULT_VARIABLE _rc)
    if(NOT _rc EQUAL 0)
        set(_id "unknown")
    endif()
endif()

string(TIMESTAMP _time "%Y-%m-%d %H:%M:%S")
set(_content "#define BUILD_ID \"${_id}\"\n#define BUILD_TIME \"${_time}\"\n")

set(_old "")
if(EXISTS "${OUT}")
    file(READ "${OUT}" _old)
endif()
if(NOT _content STREQUAL _old)
    file(WRITE "${OUT}" "${_content}")
endif()
