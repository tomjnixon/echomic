#include <msp430f2012.h>
#include <usi_i2c.h>
#include <stdlib.h>

const struct {
  uint8_t address, reg, data;
} i2c_txns[] = {
#include "i2c_txns.inc"
};

int main(void)
{
  WDTCTL = WDTPW + WDTHOLD;

  DCOCTL = 0;
  DCOCTL = CALDCO_1MHZ;
  BCSCTL1 = CALBC1_1MHZ;

  P1DIR |= 0x01;
  P1OUT |= 0x01;

  i2c_init(USIDIV_5, USISSEL_2);

  for (uint16_t i = 0; i < sizeof(i2c_txns) / sizeof(i2c_txns[0]); i++) {
    uint16_t txn[3] = {
      (uint8_t)(i2c_txns[i].address) << 1,
      i2c_txns[i].reg,
      i2c_txns[i].data
    };

    i2c_send_sequence(txn, 3, NULL, 0);
  }

  while (1) ;

  return 0;
}
