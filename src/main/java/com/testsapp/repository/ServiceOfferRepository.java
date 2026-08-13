package com.testsapp.repository;
import com.testsapp.domain.ServiceOffer;
import org.springframework.stereotype.Repository;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;
import java.util.concurrent.atomic.AtomicLong;
@Repository
public class ServiceOfferRepository {
    private final ConcurrentMap<Long, ServiceOffer> storage = new ConcurrentHashMap<>();
    private final AtomicLong idSequence = new AtomicLong(1);
    public ServiceOffer save(ServiceOffer serviceOffer) {
        if (serviceOffer.getId() == 0) {
            serviceOffer.assignId(idSequence.getAndIncrement());
        }
        storage.put(serviceOffer.getId(), serviceOffer);
        return serviceOffer;
    }
    public Optional<ServiceOffer> findById(long id) {
        return Optional.ofNullable(storage.get(id));
    }
    public List<ServiceOffer> findAll() {
        return storage.values().stream()
                .sorted(Comparator.comparingLong(ServiceOffer::getId))
                .toList();
    }
    public boolean existsByNameIgnoreCase(String name) {
        String normalized = normalize(name);
        return storage.values().stream().anyMatch(item -> normalize(item.getName()).equals(normalized));
    }
    public List<ServiceOffer> findActive() {
        return storage.values().stream()
                .filter(ServiceOffer::isActive)
                .sorted(Comparator.comparing(ServiceOffer::getName, String.CASE_INSENSITIVE_ORDER))
                .toList();
    }
    public List<ServiceOffer> findInactive() {
        return storage.values().stream()
                .filter(item -> !item.isActive())
                .sorted(Comparator.comparing(ServiceOffer::getName, String.CASE_INSENSITIVE_ORDER))
                .toList();
    }
    private String normalize(String value) {
        return value == null ? "" : value.trim().toLowerCase(Locale.ROOT);
    }
}
