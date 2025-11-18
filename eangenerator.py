import random

def genera_ean13():
    # primi 12 cifre casuali
    digits = [random.randint(0, 9) for _ in range(12)]

    # calcolo della cifra di controllo (checksum)
    # posizioni contate da sinistra, a partire da 1:
    # somma_odd  = cifre in posizione 1,3,5,7,9,11
    # somma_even = cifre in posizione 2,4,6,8,10,12
    somma_odd = sum(digits[0::2])        # indici 0,2,4,6,8,10
    somma_even = sum(digits[1::2])       # indici 1,3,5,7,9,11

    totale = somma_odd + somma_even * 3
    checksum = (10 - (totale % 10)) % 10

    digits.append(checksum)

    return ''.join(str(d) for d in digits)
