/* printf/scanf 到 USART1 的最小 retarget，其余 syscall 用空 stub（配合 --specs=nosys.specs） */
#include <sys/stat.h>
#include <stdlib.h>
#include <errno.h>
#include <stdio.h>
#include <signal.h>
#include <time.h>
#include <sys/time.h>
#include <sys/times.h>
#include "main.h"

#undef errno
extern int errno;

char *__env[1] = {0};
char **environ = __env;

void _exit(int status)
{
    (void)status;
    while (1) {}
}

int _open(char *path, int flags, ...)
{
    (void)path;
    (void)flags;
    errno = ENOSYS;
    return -1;
}

int _close(int fd)
{
    (void)fd;
    errno = ENOSYS;
    return -1;
}

int _execve(char *path, char **argv, char **envp)
{
    (void)path;
    (void)argv;
    (void)envp;
    errno = ENOMEM;
    return -1;
}

int _fork(void)
{
    errno = ENOSYS;
    return -1;
}

int _fstat(int fd, struct stat *st)
{
    (void)fd;
    st->st_mode = S_IFCHR;
    return 0;
}

int _getpid(void)
{
    return 1;
}

int _isatty(int fd)
{
    (void)fd;
    return 1;
}

int _kill(int pid, int sig)
{
    (void)pid;
    (void)sig;
    errno = EINVAL;
    return -1;
}

int _link(char *old, char *new)
{
    (void)old;
    (void)new;
    errno = EMLINK;
    return -1;
}

off_t _lseek(int fd, off_t ptr, int dir)
{
    (void)fd;
    (void)ptr;
    (void)dir;
    return 0;
}

int _unlink(char *path)
{
    (void)path;
    errno = ENOENT;
    return -1;
}

int _stat(char *path, struct stat *st)
{
    (void)path;
    st->st_mode = S_IFCHR;
    return 0;
}

clock_t _times(struct tms *buf)
{
    (void)buf;
    return -1;
}

int _wait(int *status)
{
    (void)status;
    errno = ECHILD;
    return -1;
}

int _gettimeofday(struct timeval *tv, void *tzp)
{
    (void)tv;
    (void)tzp;
    return 0;
}

ssize_t _write(int fd, const void *buf, size_t len)
{
    (void)fd;
    extern UART_HandleTypeDef huart1;
    HAL_UART_Transmit(&huart1, (uint8_t *)buf, (uint16_t)len, 0xFFFF);
    return (ssize_t)len;
}

ssize_t _read(int fd, void *buf, size_t len)
{
    (void)fd;
    (void)buf;
    (void)len;
    return 0;
}
