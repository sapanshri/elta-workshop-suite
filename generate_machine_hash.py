import uuid
import hashlib

machine_hash = hashlib.sha256(
    str(uuid.getnode()).encode()
).hexdigest()

print("MACHINE HASH:")
print(machine_hash)

