package com.testsapp.service;

import com.testsapp.domain.Appointment;
import com.testsapp.domain.ServiceOffer;
import com.testsapp.dto.CreateServiceOfferRequest;
import com.testsapp.dto.ServiceOfferResponse;
import com.testsapp.exception.ApiException;
import com.testsapp.repository.AppointmentRepository;
import com.testsapp.repository.ServiceOfferRepository;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ServiceOfferServiceTest {

    @Mock
    ServiceOfferRepository serviceOfferRepository;

    @Mock
    AppointmentRepository appointmentRepository;

    @InjectMocks
    ServiceOfferService serviceOfferService;

    private ServiceOffer offer(String name, int durationMinutes, String price, boolean active, long id) {
        ServiceOffer offer = new ServiceOffer(name, durationMinutes, new BigDecimal(price), active);
        offer.assignId(id);
        return offer;
    }

    private Appointment futureScheduledAppointment(long serviceOfferId) {
        LocalDateTime start = LocalDateTime.now().plusDays(1).withSecond(0).withNano(0);
        Appointment appointment = new Appointment(
                serviceOfferId,
                "Haircut",
                "John Doe",
                "john@example.com",
                start,
                start.plusMinutes(30),
                new BigDecimal("100.00"),
                null
        );
        appointment.assignId(100L);
        return appointment;
    }

    // TC02
    @Test
    @DisplayName("listAll returns all offers mapped to ServiceOfferResponse when repository has entries")
    void listAll_returnsMappedResponses_whenRepositoryHasOffers() {
        ServiceOffer first = offer("Haircut", 30, "100.00", true, 1L);
        ServiceOffer second = offer("Beard Trim", 45, "80.00", false, 2L);
        when(serviceOfferRepository.findAll()).thenReturn(List.of(first, second));

        List<ServiceOfferResponse> result = serviceOfferService.listAll();

        assertThat(result).hasSize(2);
        assertThat(result.get(0).id()).isEqualTo(1L);
        assertThat(result.get(0).name()).isEqualTo("Haircut");
        assertThat(result.get(1).id()).isEqualTo(2L);
        assertThat(result.get(1).active()).isFalse();
    }

    // TC03
    @Test
    @DisplayName("listActive returns only active offers (inactive offers excluded)")
    void listActive_returnsOnlyActiveOffers() {
        ServiceOffer active = offer("Haircut", 30, "100.00", true, 1L);
        ServiceOffer inactive = offer("Coloring", 60, "150.00", false, 2L);
        when(serviceOfferRepository.findActive()).thenReturn(List.of(active));

        List<ServiceOfferResponse> result = serviceOfferService.listActive();

        assertThat(result).hasSize(1);
        assertThat(result.get(0).id()).isEqualTo(active.getId());
        assertThat(result.get(0).active()).isTrue();
        assertThat(result).allMatch(ServiceOfferResponse::active);
        assertThat(result).noneMatch(r -> r.id() == inactive.getId());
    }

    // TC04
    @Test
    @DisplayName("create succeeds with valid request - returns response with active=true, trimmed name, price scaled to 2 dp")
    void create_succeeds_withValidRequest_andNormalizesNameAndPrice() {
        CreateServiceOfferRequest request = new CreateServiceOfferRequest("  Haircut  ", 30, new BigDecimal("99.999"));
        when(serviceOfferRepository.existsByNameIgnoreCase(request.name())).thenReturn(false);
        when(serviceOfferRepository.save(any(ServiceOffer.class))).thenAnswer(invocation -> {
            ServiceOffer saved = invocation.getArgument(0);
            saved.assignId(1L);
            return saved;
        });

        ServiceOfferResponse result = serviceOfferService.create(request);

        ArgumentCaptor<ServiceOffer> captor = ArgumentCaptor.forClass(ServiceOffer.class);
        verify(serviceOfferRepository).save(captor.capture());
        ServiceOffer persisted = captor.getValue();

        assertThat(persisted.getName()).isEqualTo("Haircut");
        assertThat(persisted.getBasePrice()).isEqualByComparingTo(new BigDecimal("100.00"));
        assertThat(persisted.isActive()).isTrue();

        assertThat(result.id()).isEqualTo(1L);
        assertThat(result.name()).isEqualTo("Haircut");
        assertThat(result.basePrice()).isEqualByComparingTo(new BigDecimal("100.00"));
        assertThat(result.active()).isTrue();
    }

    // TC14
    @Test
    @DisplayName("create throws CONFLICT when a service with the same name already exists (case-insensitive duplicate)")
    void create_throwsConflict_whenDuplicateNameExistsCaseInsensitive() {
        CreateServiceOfferRequest request = new CreateServiceOfferRequest("haircut", 30, new BigDecimal("100.00"));
        when(serviceOfferRepository.existsByNameIgnoreCase("haircut")).thenReturn(true);

        assertThatThrownBy(() -> serviceOfferService.create(request))
                .isInstanceOf(ApiException.class)
                .satisfies(ex -> assertThat(((ApiException) ex).getStatus()).isEqualTo(HttpStatus.CONFLICT));
    }

    // TC15
    @Test
    @DisplayName("activate sets offer.active=true, saves and returns updated response")
    void activate_setsOfferActive_andReturnsResponse() {
        ServiceOffer inactiveOffer = offer("Haircut", 30, "100.00", false, 1L);
        when(serviceOfferRepository.findById(1L)).thenReturn(Optional.of(inactiveOffer));
        when(serviceOfferRepository.save(inactiveOffer)).thenReturn(inactiveOffer);

        ServiceOfferResponse result = serviceOfferService.activate(1L);

        assertThat(inactiveOffer.isActive()).isTrue();
        assertThat(result.id()).isEqualTo(1L);
        assertThat(result.active()).isTrue();
    }

    // TC17
    @Test
    @DisplayName("deactivate sets offer.active=false, saves and returns updated response when no future appointments exist")
    void deactivate_setsOfferInactive_whenNoFutureAppointments() {
        ServiceOffer activeOffer = offer("Haircut", 30, "100.00", true, 1L);
        when(serviceOfferRepository.findById(1L)).thenReturn(Optional.of(activeOffer));
        when(appointmentRepository.findFutureActiveByService(1L, any(LocalDateTime.class))).thenReturn(List.of());
        when(serviceOfferRepository.save(activeOffer)).thenReturn(activeOffer);

        ServiceOfferResponse result = serviceOfferService.deactivate(1L);

        assertThat(activeOffer.isActive()).isFalse();
        assertThat(result.id()).isEqualTo(1L);
        assertThat(result.active()).isFalse();
    }

    // TC19
    @Test
    @DisplayName("deactivate throws CONFLICT when future SCHEDULED appointments exist for this service")
    void deactivate_throwsConflict_whenFutureScheduledAppointmentsExist() {
        ServiceOffer activeOffer = offer("Haircut", 30, "100.00", true, 1L);
        when(serviceOfferRepository.findById(1L)).thenReturn(Optional.of(activeOffer));
        when(appointmentRepository.findFutureActiveByService(1L, any(LocalDateTime.class)))
                .thenReturn(List.of(futureScheduledAppointment(1L)));

        assertThatThrownBy(() -> serviceOfferService.deactivate(1L))
                .isInstanceOf(ApiException.class)
                .satisfies(ex -> assertThat(((ApiException) ex).getStatus()).isEqualTo(HttpStatus.CONFLICT));

        verify(serviceOfferRepository, never()).save(any(ServiceOffer.class));
    }
}

