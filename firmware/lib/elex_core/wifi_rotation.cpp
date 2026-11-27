#include "wifi_rotation.h"

namespace elex {

size_t WifiRotation::next() {
    last_ = (preferred_ + pos_) % count_;
    if (pos_ < count_) pos_++;
    return last_;
}

}  // namespace elex
