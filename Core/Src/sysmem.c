/* newlib 堆管理：_sbrk（heap 在 .bss 之后到栈底之间） */
#include <errno.h>
#include <stddef.h>
#include <stdint.h>

extern uint8_t _end;    /* 链接脚本提供：heap 起始（.bss 结束） */
extern uint8_t _estack; /* 栈顶 */

static uint8_t *heap_ptr = NULL;

void *_sbrk(ptrdiff_t incr)
{
    uint8_t *prev;
    uint8_t *sp = (uint8_t *)&prev; /* 近似当前栈位置 */

    if (heap_ptr == NULL)
    {
        heap_ptr = &_end;
    }
    prev = heap_ptr;
    if ((prev + incr > &_estack) || (prev + incr <= sp)) /* &_estack=符号值(RAM顶)，直接写 _estack 会变成读 0x20020000 越一字节→BusFault */
    {
        errno = ENOMEM;
        return (void *)-1;
    }
    heap_ptr += incr;
    return prev;
}
