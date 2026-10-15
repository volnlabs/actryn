// SPDX-License-Identifier: GPL-2.0-only
#include <kunit/test.h>
#include "actryn_wire.h"
#include "actryn_control.h"

static void wire_roundtrip(struct kunit *test)
{
 struct actryn_frame f={.kind=AW_SAMPLE,.left=-200,.right=200}, decoded;
 u8 encoded[ACTRYN_ENCODED_MAX]; size_t n=actryn_encode(&f,encoded),i;
 KUNIT_EXPECT_EQ(test,actryn_decode(encoded,n-1,&decoded),0);
 KUNIT_EXPECT_EQ(test,decoded.left,-200);
 for(i=0;i<n-1;i++) KUNIT_EXPECT_LT(test,actryn_decode(encoded,i,&decoded),0);
 encoded[10]^=0x80;
 KUNIT_EXPECT_LT(test,actryn_decode(encoded,n-1,&decoded),0);
 KUNIT_EXPECT_LT(test,actryn_window(100,100,10),0);
}
static void urgent_monotonic(struct kunit *test)
{
 struct actryn_close slot={0}; u64 serial=0,revision;
 KUNIT_ASSERT_EQ(test,actryn_merge_close(&slot,1,1,10,20,10,20,&serial),0);
 revision=slot.revision;
 KUNIT_ASSERT_EQ(test,actryn_merge_close(&slot,1,2,10,20,10,20,&serial),0);
 KUNIT_EXPECT_EQ(test,slot.reason,1U);
 KUNIT_EXPECT_EQ(test,actryn_merge_close(&slot,2,3,9,20,10,20,&serial),-1);
 KUNIT_ASSERT_EQ(test,actryn_merge_close(&slot,3,7,0,0,10,20,&serial),0);
 actryn_clear_close(&slot,revision);
 KUNIT_EXPECT_EQ(test,slot.rank,3U);
 KUNIT_ASSERT_EQ(test,actryn_merge_close(&slot,1,2,10,20,10,20,&serial),0);
 KUNIT_EXPECT_EQ(test,slot.rank,3U);
}
static struct kunit_case cases[]={ KUNIT_CASE(wire_roundtrip),KUNIT_CASE(urgent_monotonic),{} };
static struct kunit_suite suite={ .name="actryn-authority",.test_cases=cases };
kunit_test_suite(suite);
MODULE_LICENSE("GPL");
